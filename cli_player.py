import sys
import os
import re
import time
import curses

try:
    import mpv
except ImportError:
    print("Błąd: Nie znaleziono modułu 'mpv'.")
    print("Upewnij się, że zainstalowałeś pakiety wpisując: sudo pacman -S mpv python-mpv")
    sys.exit(1)

class MpvLrcPlayer:
    def __init__(self, stdscr, start_file):
        self.stdscr = stdscr
        # Budowanie playlisty z katalogu
        self.dir = os.path.dirname(os.path.abspath(start_file))
        self.playlist = sorted([f for f in os.listdir(self.dir) if f.lower().endswith('.mp3')])
        
        try:
            self.current_idx = self.playlist.index(os.path.basename(start_file))
        except ValueError:
            self.current_idx = 0
            if self.playlist:
                start_file = os.path.join(self.dir, self.playlist[0])

        self.lyrics = []
        self.time_pos = 0.0
        self.duration = 0.0
        self.needs_next = False
        
        # Konfiguracja silnika MPV (bez GUI i wideo)
        self.player = mpv.MPV(ytdl=False, video=False)
        
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
        # Definicje par kolorów (Tekst, Tło)
        curses.init_pair(1, curses.COLOR_GREEN, -1)   # Aktywny wers
        curses.init_pair(2, curses.COLOR_WHITE, -1)   # Standardowy (i przygaszony)
        curses.init_pair(3, curses.COLOR_CYAN, -1)    # Paski informacji

        # Start odtwarzania
        self.load_track()

    def parse_lrc(self, file_path):
        """Parsuje .lrc, wyciąga offset i obsługuje powielone timestampy."""
        lyrics = []
        if not os.path.exists(file_path):
            return lyrics

        offset = 0.0
        # Wyrażenia regularne
        pattern_offset = re.compile(r'\[offset:([+-]?\d+)\]', re.IGNORECASE)
        pattern_time = re.compile(r'\[(\d{2}):(\d{2}(?:\.\d+)?)\]')

        with open(file_path, 'r', encoding='utf-8') as f:
            for line in f:
                # 1. Obsługa tagu offset (przesunięcie w milisekundach)
                match_offset = pattern_offset.search(line)
                if match_offset:
                    offset = float(match_offset.group(1)) / 1000.0
                    continue
                
                # 2. Szukanie wszystkich timestampów w danej linii (obsługa wielu znaczników)
                timestamps = pattern_time.findall(line)
                if timestamps:
                    # Wycinanie znaczników, żeby uzyskać czysty tekst
                    text = pattern_time.sub('', line).strip()
                    for mins, secs in timestamps:
                        total_time = (int(mins) * 60) + float(secs) + offset
                        # Zabezpieczenie przed ujemnym czasem po modyfikacji offsetem
                        lyrics.append((max(0.0, total_time), text))
        
        # Sortowanie według czasu (wymagane przy zagnieżdżonych i powielonych znacznikach)
        lyrics.sort(key=lambda x: x[0])
        return lyrics

    def load_track(self):
        if not self.playlist: return
        file_name = self.playlist[self.current_idx]
        mp3_path = os.path.join(self.dir, file_name)
        
        # Automatyczne ładowanie pliku o identycznej nazwie z .lrc
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

            # Czyszczenie i przeliczanie rozmiaru (pozwala na odświeżanie po zmianie terminala)
            self.stdscr.erase()
            height, width = self.stdscr.getmaxyx()

            # Zabezpieczenie na wypadek ekstremalnie małego terminala
            if height < 10 or width < 40:
                self.stdscr.addstr(0, 0, "Zbyt małe okno!")
                self.stdscr.refresh()
                time.sleep(0.1)
                continue

            # --- GÓRNY PANEL: Tytuł utworu ---
            track_name = self.playlist[self.current_idx] if self.playlist else "Brak plików"
            title_str = f" MPV Player | {track_name} ({self.current_idx + 1}/{len(self.playlist)}) "
            self.stdscr.addstr(0, max(0, width//2 - len(title_str)//2), title_str, curses.color_pair(3) | curses.A_BOLD)

            # --- GÓRNY PANEL: Pasek postępu ---
            time_str = f" {self.format_time(self.time_pos)} / {self.format_time(self.duration)} "
            bar_width = width - len(time_str) - 4
            if bar_width > 0:
                progress = min(1.0, max(0.0, self.time_pos / self.duration)) if self.duration > 0 else 0.0
                filled = int(bar_width * progress)
                bar = "[" + "=" * filled + ">" + " " * (bar_width - filled - 1) + "]"
                self.stdscr.addstr(2, 2, bar + time_str, curses.color_pair(2))

            # --- GÓRNY PANEL: Status i Głośność ---
            vol = getattr(self.player, 'volume', 100.0)
            mute = getattr(self.player, 'mute', False)
            pause = getattr(self.player, 'pause', False)
            
            vol_str = f"Głośność: {'WYCISZONY' if mute else f'{int(vol)}%'}"
            state_str = "PAUZA" if pause else "ODTWARZANIE"
            self.stdscr.addstr(3, 2, f"{vol_str} | {state_str}", curses.color_pair(2) | curses.A_BOLD)
            self.stdscr.hline(4, 0, curses.ACS_HLINE, width)

            # --- ŚRODKOWY PANEL: Wyśrodkowane i przygaszane napisy ---
            if not self.lyrics:
                msg = "Nie znaleziono tekstu (pliku .lrc) dla tego utworu."
                self.stdscr.addstr(height // 2, max(0, width//2 - len(msg)//2), msg, curses.color_pair(2) | curses.A_DIM)
            else:
                # Detekcja aktualnej linii
                current_index = -1
                for i, (timestamp, text) in enumerate(self.lyrics):
                    if self.time_pos >= timestamp:
                        current_index = i
                    else:
                        break

                center_y = height // 2 + 1
                visible_lines = (height - 8) // 2  # Odstępy na interfejs

                start_idx = max(0, current_index - visible_lines)
                end_idx = min(len(self.lyrics), current_index + visible_lines + 1)

                row_y = center_y - (current_index - start_idx) if current_index >= 0 else center_y - (-start_idx)

                for i in range(start_idx, end_idx):
                    if 5 <= row_y < height - 2:
                        text = self.lyrics[i][1]
                        col_x = max(0, width // 2 - len(text) // 2)
                        
                        if i == current_index:
                            # Bieżąca linia - podświetlenie na zielono
                            self.stdscr.attron(curses.color_pair(1) | curses.A_BOLD)
                            self.stdscr.addstr(row_y, col_x, text)
                            self.stdscr.attroff(curses.color_pair(1) | curses.A_BOLD)
                        else:
                            # Poprzednie i następne linie - przygaszone (A_DIM)
                            self.stdscr.attron(curses.color_pair(2) | curses.A_DIM)
                            self.stdscr.addstr(row_y, col_x, text)
                            self.stdscr.attroff(curses.color_pair(2) | curses.A_DIM)
                    row_y += 1

            # --- DOLNY PANEL: Klawiszologia ---
            help_str = " ←/→:Przewijaj | ↑/↓:Głośność | Spacja:Pauza | m:Wycisz | n/p:Nast/Poprz | Home/End | q:Wyjście "
            self.stdscr.addstr(height - 1, max(0, width//2 - len(help_str)//2), help_str, curses.color_pair(3) | curses.A_REVERSE)

            # Wysłanie klatki na ekran
            self.stdscr.refresh()

            # --- OBSŁUGA KLAWISZY ---
            c = self.stdscr.getch()
            if c == ord('q'):
                break
            elif c == curses.KEY_RESIZE:
                pass # Curses automatycznie wychwyci nowy rozmiar w pętli głównej
            elif c == curses.KEY_LEFT:
                self.player.time_pos = max(0.0, self.time_pos - 5.0)
            elif c == curses.KEY_RIGHT:
                if self.duration: self.player.time_pos = min(self.duration, self.time_pos + 5.0)
            elif c == curses.KEY_UP:
                self.player.volume = min(130.0, vol + 5.0) # MPV pozwala na >100% głośności
            elif c == curses.KEY_DOWN:
                self.player.volume = max(0.0, vol - 5.0)
            elif c == ord(' '):
                self.player.pause = not pause
            elif c == ord('m'):
                self.player.mute = not mute
            elif c in [curses.KEY_HOME, 262]: # 262 to rzadki kod alternatywny dla HOME na niektórych emulatorach
                self.player.time_pos = 0.0
            elif c in [curses.KEY_END, 360]:
                # Pozwala naturalnie wyzwolić przejście utworu tuż przy końcu
                if self.duration: self.player.time_pos = max(0.0, self.duration - 1.0)
            elif c == ord('n'):
                self.next_track()
            elif c == ord('p'):
                self.prev_track()

            # Zatrzymanie pętli na 50ms - utrzymuje około 20 FPS przy minimalnym zużyciu procesora
            time.sleep(0.05)

        # Ubicie procesu mpv podczas wychodzenia
        self.player.terminate()

def main(stdscr, start_file):
    MpvLrcPlayer(stdscr, start_file).run()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Użycie: python mpv_cli_player.py <nazwa_pliku.mp3>")
        sys.exit(1)

    start_file = sys.argv[1]
    
    if not os.path.exists(start_file):
        print(f"Błąd: Nie znaleziono pliku: {start_file}")
        sys.exit(1)

    # Curses wrapper gwarantuje, że terminal powróci do normalnego stanu w przypadku awarii
    curses.wrapper(main, start_file)

if __name__ == "__main__":
    # Jeśli nie podano argumentu, program użyje bieżącego katalogu
    if len(sys.argv) < 2:
        target_path = os.getcwd()
    else:
        target_path = sys.argv[1]

    if not os.path.exists(target_path):
        print(f"Błąd: Ścieżka nie istnieje: {target_path}")
        sys.exit(1)

    # Uruchomienie programu
    error_msg = curses.wrapper(main, target_path)
    if error_msg:
        print(f"Błąd uruchamiania: {error_msg}")