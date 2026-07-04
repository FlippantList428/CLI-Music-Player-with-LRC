import sys
import os
import re
import time
import curses
import io
import locale

try:
    import mpv
    from mutagen.id3 import ID3
    from PIL import Image
except ImportError:
    print("Błąd: Nie znaleziono wymaganych modułów ('mpv', 'mutagen', 'PIL').")
    print("Upewnij się, że zainstalowałeś pakiety wpisując:")
    print("Arch Linux: sudo pacman -S mpv python-mpv python-mutagen python-pillow")
    print("Ubuntu/Mint: sudo apt install mpv python3-mpv python3-mutagen python3-pil")
    sys.exit(1)


# --- Pomocnicze funkcje do wyświetlania naprawdę "powiększonego" tekstu ---
# curses nie potrafi zmieniać rozmiaru fontu per-znak, ale znaki z bloku
# Unicode "Fullwidth Forms" zajmują na ekranie 2 kolumny zamiast jednej,
# dzięki czemu aktualny wers wygląda realnie większy (a nie tylko oznaczony
# strzałkami).

def to_fullwidth(text):
    """Konwertuje standardowe znaki ASCII na ich szerokie odpowiedniki Unicode."""
    result = []
    for ch in text:
        code = ord(ch)
        if ch == ' ':
            result.append('\u3000')
        elif 0x21 <= code <= 0x7E:
            result.append(chr(code + 0xFEE0))
        else:
            # Polskie znaki diakrytyczne itp. nie mają odpowiednika "fullwidth"
            # i zostają w oryginalnej (węższej) formie.
            result.append(ch)
    return ''.join(result)


def display_width(text):
    """Zwraca szerokość tekstu w kolumnach terminala (znaki 'fullwidth' liczą się podwójnie)."""
    width = 0
    for ch in text:
        code = ord(ch)
        if code == 0x3000 or 0xFF00 <= code <= 0xFFEF:
            width += 2
        else:
            width += 1
    return width



class MpvLrcPlayer:
    def __init__(self, stdscr, start_file):
        self.stdscr = stdscr
        
        # Poprawna obsługa ścieżek z innych lokalizacji
        abs_path = os.path.abspath(start_file)
        if os.path.isdir(abs_path):
            self.dir = abs_path
            target_basename = None
        else:
            self.dir = os.path.dirname(abs_path)
            target_basename = os.path.basename(abs_path)

        self.playlist = sorted([f for f in os.listdir(self.dir) if f.lower().endswith('.mp3')])
        
        self.current_idx = 0
        if target_basename and target_basename in self.playlist:
            self.current_idx = self.playlist.index(target_basename)

        self.lyrics = []
        self.metadata = {'artist': 'Nieznany', 'album': 'Nieznany'}
        self.ascii_art = []
        self.time_pos = 0.0
        self.duration = 0.0
        self.needs_next = False
        
        # Konfiguracja silnika MPV (bez GUI i wideo).
        # idle=True utrzymuje rdzeń mpv aktywny po zakończeniu utworu, dzięki
        # czemu automatyczne przejście do kolejnej ścieżki działa niezawodnie
        # niezależnie od tego, czy program uruchomiono z plikiem, czy z katalogiem.
        self.player = mpv.MPV(ytdl=False, video=False, idle=True)
        
        # Obserwatory (MPV aktualizuje wartości asynchronicznie)
        @self.player.property_observer('time-pos')
        def time_observer(_name, value):
            self.time_pos = value if value is not None else 0.0

        @self.player.property_observer('duration')
        def dur_observer(_name, value):
            self.duration = value if value is not None else 0.0

        @self.player.property_observer('eof-reached')
        def eof_observer(_name, value):
            if value:
                self.needs_next = True

        # Inicjalizacja curses
        curses.curs_set(0)
        self.stdscr.nodelay(1)
        curses.start_color()
        curses.use_default_colors()
        
        # Definicje głównych par kolorów (Tekst, Tło)
        curses.init_pair(1, curses.COLOR_GREEN, -1)   # Aktywny wers
        curses.init_pair(2, curses.COLOR_WHITE, -1)   # Standardowy (i przygaszony)
        curses.init_pair(3, curses.COLOR_CYAN, -1)    # Paski informacji
        curses.init_pair(4, curses.COLOR_RED, -1)     # Czerwony dla braku tekstu
        
        # Definicje kolorów dla ASCII artu (Pary 11-17, mapowanie z RGB)
        for i in range(1, 8):
            curses.init_pair(10 + i, i, -1)

        # Start odtwarzania
        self.load_track()

    def parse_lyrics_text(self, text):
        """Uniwersalna metoda wyciągająca czas i tekst z podanego ciągu znaków."""
        lyrics = []
        offset = 0.0
        pattern_offset = re.compile(r'\[offset:([+-]?\d+)\]', re.IGNORECASE)
        pattern_time = re.compile(r'\[(\d{2}):(\d{2}(?:\.\d+)?)\]')

        for line in text.splitlines():
            match_offset = pattern_offset.search(line)
            if match_offset:
                offset = float(match_offset.group(1)) / 1000.0
                continue
            
            timestamps = pattern_time.findall(line)
            if timestamps:
                txt = pattern_time.sub('', line).strip()
                for mins, secs in timestamps:
                    total_time = (int(mins) * 60) + float(secs) + offset
                    lyrics.append((max(0.0, total_time), txt))
        
        lyrics.sort(key=lambda x: x[0])
        return lyrics

    def parse_lrc(self, file_path):
        if not os.path.exists(file_path):
            return []
        with open(file_path, 'r', encoding='utf-8') as f:
            return self.parse_lyrics_text(f.read())

    def load_track(self):
        if not self.playlist: return
        file_name = self.playlist[self.current_idx]
        mp3_path = os.path.join(self.dir, file_name)
        
        self.metadata = {'artist': 'Nieznany', 'album': 'Nieznany'}
        self.ascii_art = []
        uslt_lyrics = []

        try:
            audio = ID3(mp3_path)
            self.metadata['artist'] = str(audio.get('TPE1', 'Nieznany'))
            self.metadata['album'] = str(audio.get('TALB', 'Nieznany'))
            
            uslt = audio.getall('USLT')
            if uslt:
                uslt_lyrics = self.parse_lyrics_text(uslt[0].text)
                
            # Ekstrakcja i konwersja okładki na KOLOROWE ASCII
            apic = audio.getall('APIC')
            if apic:
                img = Image.open(io.BytesIO(apic[0].data)).convert('RGB').resize((24, 10))
                chars = "@%#*+=-:. "
                for y in range(img.height):
                    line_data = []
                    for x in range(img.width):
                        r, g, b = img.getpixel((x, y))
                        
                        # Znalezienie odpowiedniego koloru z palety terminala
                        color_idx = (1 if r > 127 else 0) | (2 if g > 127 else 0) | (4 if b > 127 else 0)
                        if color_idx == 0: color_idx = 7 # Jeśli jest czarny, wymuś biały by był widoczny
                        
                        # Dopasowanie odpowiedniego znaku pod względem jasności
                        brightness = (r + g + b) // 3
                        char_idx = brightness // 28
                        char = chars[char_idx] if char_idx < len(chars) else chars[-1]
                        
                        line_data.append((char, 10 + color_idx))
                    self.ascii_art.append(line_data)
        except Exception:
            pass
        
        if uslt_lyrics:
            self.lyrics = uslt_lyrics
        else:
            lrc_path = os.path.splitext(mp3_path)[0] + ".lrc"
            self.lyrics = self.parse_lrc(lrc_path)
        
        self.time_pos = 0.0
        self.duration = 0.0
        self.needs_next = False
        
        self.player.play(mp3_path)

    def next_track(self):
        if self.playlist:
            self.current_idx = (self.current_idx + 1) % len(self.playlist)
            self.load_track()

    def prev_track(self):
        if self.playlist:
            self.current_idx = (self.current_idx - 1) % len(self.playlist)
            self.load_track()
            
    def format_time(self, seconds):
        if seconds < 0: seconds = 0
        m, s = divmod(int(seconds), 60)
        return f"{m:02d}:{s:02d}"

    def run(self):
        while True:
            # Automatyczne przejście do następnego utworu
            if self.needs_next:
                self.next_track()

            self.stdscr.erase()
            height, width = self.stdscr.getmaxyx()

            if height < 10 or width < 40:
                self.stdscr.addstr(0, 0, "Zbyt małe okno!")
                self.stdscr.refresh()
                time.sleep(0.1)
                continue

            # --- GÓRNY PANEL ---
            track_name = self.playlist[self.current_idx] if self.playlist else "Brak plików"
            title_str = f" MPV Player | {track_name} ({self.current_idx + 1}/{len(self.playlist)}) "
            self.stdscr.addstr(0, max(0, width//2 - len(title_str)//2), title_str, curses.color_pair(3) | curses.A_BOLD)

            time_str = f" {self.format_time(self.time_pos)} / {self.format_time(self.duration)} "
            bar_width = width - len(time_str) - 4
            if bar_width > 0:
                progress = min(1.0, max(0.0, self.time_pos / self.duration)) if self.duration > 0 else 0.0
                filled = int(bar_width * progress)
                bar = "[" + "=" * filled + ">" + " " * (bar_width - filled - 1) + "]"
                self.stdscr.addstr(2, 2, bar + time_str, curses.color_pair(2))

            vol = getattr(self.player, 'volume', 100.0)
            mute = getattr(self.player, 'mute', False)
            pause = getattr(self.player, 'pause', False)
            
            vol_str = f"Głośność: {'WYCISZONY' if mute else f'{int(vol)}%'}"
            state_str = "PAUZA" if pause else "ODTWARZANIE"
            self.stdscr.addstr(3, 2, f"{vol_str} | {state_str}", curses.color_pair(2) | curses.A_BOLD)
            self.stdscr.hline(4, 0, curses.ACS_HLINE, width)

            # --- PANEL INFORMACYJNY: Autor, Album i Miniaturka Kolorowego ASCII ---
            meta_str = f"Autor: {self.metadata['artist']} | Album: {self.metadata['album']}"
            if 5 < height - 2:
                self.stdscr.addstr(5, 2, meta_str[:width-4], curses.color_pair(3) | curses.A_BOLD)
            
            for i, line_data in enumerate(self.ascii_art):
                row = 6 + i
                if row < height - 2:
                    for j, (char, color_idx) in enumerate(line_data):
                        try:
                            self.stdscr.addstr(row, 2 + j, char, curses.color_pair(color_idx))
                        except curses.error:
                            pass # Zabezpieczenie przy rysowaniu na krawędziach

            # --- ŚRODKOWY PANEL: Wyśrodkowane i przygaszane napisy ---
            top_margin = 6 + len(self.ascii_art) # Wyliczenie marginesu tak, aby nie nachodziło na obraz

            if not self.lyrics:
                msg = "BRAK TEKSTU"
                row_y = max(top_margin, min(height // 2, height - 3))
                self.stdscr.attron(curses.color_pair(4) | curses.A_BOLD)
                try:
                    self.stdscr.addstr(row_y, max(0, width // 2 - len(msg) // 2), msg)
                except curses.error:
                    pass
                self.stdscr.attroff(curses.color_pair(4) | curses.A_BOLD)
            else:
                current_index = -1
                for i, (timestamp, text) in enumerate(self.lyrics):
                    if self.time_pos >= timestamp:
                        current_index = i
                    else:
                        break

                # Środek dopasowujący się tak, aby pominąć górną grafikę
                center_y = max(top_margin + 2, height // 2)
                visible_lines = max(1, (height - center_y - 2))

                start_idx = max(0, current_index - visible_lines)
                end_idx = min(len(self.lyrics), current_index + visible_lines + 1)

                row_y = center_y - (current_index - start_idx) if current_index >= 0 else center_y - (-start_idx)

                for i in range(start_idx, end_idx):
                    if top_margin <= row_y < height - 2:
                        text = self.lyrics[i][1]
                        
                        if i == current_index:
                            # Bieżący wers: realnie powiększony (znaki "fullwidth"
                            # zajmują 2 kolumny terminala) i dodatkowo obramowany
                            # strzałkami dla jeszcze lepszej widoczności.
                            big_text = to_fullwidth(text)
                            highlighted_text = f"▶ {big_text} ◀"
                            total_width = display_width(highlighted_text)
                            col_x = max(0, width // 2 - total_width // 2)
                            self.stdscr.attron(curses.color_pair(1) | curses.A_BOLD)
                            try: self.stdscr.addstr(row_y, col_x, highlighted_text)
                            except curses.error: pass
                            self.stdscr.attroff(curses.color_pair(1) | curses.A_BOLD)
                        else:
                            # Przygaszone, mniejsze pozostałe wersy
                            col_x = max(0, width // 2 - len(text) // 2)
                            self.stdscr.attron(curses.color_pair(2) | curses.A_DIM)
                            try: self.stdscr.addstr(row_y, col_x, text)
                            except curses.error: pass
                            self.stdscr.attroff(curses.color_pair(2) | curses.A_DIM)
                    row_y += 1

            # --- DOLNY PANEL: Klawiszologia ---
            help_str = " ←/→:Przewijaj | ↑/↓:Głośność | Spacja:Pauza | m:Wycisz | n/p:Nast/Poprz | Home/End | q:Wyjście "
            self.stdscr.addstr(height - 1, max(0, width//2 - len(help_str)//2), help_str, curses.color_pair(3) | curses.A_REVERSE)

            self.stdscr.refresh()

            # --- OBSŁUGA KLAWISZY ---
            c = self.stdscr.getch()
            if c == ord('q'):
                break
            elif c == curses.KEY_RESIZE:
                pass
            elif c == curses.KEY_LEFT:
                self.player.time_pos = max(0.0, self.time_pos - 5.0)
            elif c == curses.KEY_RIGHT:
                if self.duration: self.player.time_pos = min(self.duration, self.time_pos + 5.0)
            elif c == curses.KEY_UP:
                self.player.volume = min(130.0, vol + 5.0)
            elif c == curses.KEY_DOWN:
                self.player.volume = max(0.0, vol - 5.0)
            elif c == ord(' '):
                self.player.pause = not pause
            elif c == ord('m'):
                self.player.mute = not mute
            elif c in [curses.KEY_HOME, 262]:
                self.player.time_pos = 0.0
            elif c in [curses.KEY_END, 360]:
                if self.duration: self.player.time_pos = max(0.0, self.duration - 1.0)
            elif c == ord('n'):
                self.next_track()
            elif c == ord('p'):
                self.prev_track()

            time.sleep(0.05)

        self.player.terminate()

def main(stdscr, target_path):
    MpvLrcPlayer(stdscr, target_path).run()

if __name__ == "__main__":
    # Ustawienie lokalnego locale (UTF-8) jest wymagane, żeby ncurses poprawnie
    # obliczał szerokość znaków Unicode (polskie znaki diakrytyczne oraz
    # szerokie znaki "fullwidth" użyte do powiększenia aktualnej linii tekstu).
    locale.setlocale(locale.LC_ALL, '')

    if len(sys.argv) < 2:
        target = os.getcwd()
    else:
        # Prawidłowo buduje ścieżkę do pliku docelowego spoza bieżącego folderu
        target = os.path.abspath(sys.argv[1])

    if not os.path.exists(target):
        print(f"Błąd: Ścieżka nie istnieje: {target}")
        sys.exit(1)

    error_msg = curses.wrapper(main, target)
    if error_msg:
        print(f"Błąd uruchamiania: {error_msg}")