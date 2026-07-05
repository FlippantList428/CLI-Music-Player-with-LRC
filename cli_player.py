#!/usr/bin/env python3

import sys
import os
import re
import time
import curses
import io
import random

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

# Tryby powtarzania
REPEAT_OFF = 0
REPEAT_ALL = 1
REPEAT_ONE = 2
REPEAT_LABELS = {REPEAT_OFF: "WYŁ", REPEAT_ALL: "WSZYSTKO", REPEAT_ONE: "JEDEN"}


class MpvLrcPlayer:
    def __init__(self, stdscr, start_file):
        """
        Uwaga dot. wydajności: playlista jest budowana jednorazowo przez
        os.listdir() i trzymana w całości w pamięci. Dla bibliotek rzędu
        dziesiątek tysięcy plików MP3 w jednym katalogu rozważ podział na
        mniejsze foldery lub indeksowanie zamiast jednorazowego listowania.
        """
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
        self.auto_next = True

        # Shuffle: "worek" z nieodtworzonymi indeksami + historia (dla 'p')
        self.shuffle = False
        self.shuffle_bag = []
        self.history = []

        # Powtarzanie: WYŁ / WSZYSTKO / JEDEN
        self.repeat_mode = REPEAT_ALL

        # Auto-pomijanie uszkodzonych/nieodtwarzalnych plików
        self.skip_bad_files = True
        self.bad_file = False
        self.failed_attempts = 0
        self.load_time = 0.0
        
        # Konfiguracja silnika MPV (bez GUI i wideo)
        self.player = mpv.MPV(ytdl=False, video=False)
        
        # Obserwatory (MPV aktualizuje wartości asynchronicznie)
        @self.player.property_observer('time-pos')
        def time_observer(_name, value):
            self.time_pos = value if value is not None else 0.0

        @self.player.property_observer('duration')
        def dur_observer(_name, value):
            self.duration = value if value is not None else 0.0
            if self.duration > 0:
                # Plik faktycznie się odtwarza - reset licznika błędów pod rząd
                self.failed_attempts = 0

        @self.player.property_observer('eof-reached')
        def eof_observer(_name, value):
            if not value:
                return
            # Jeśli plik zakończył się natychmiast bez ustalenia długości,
            # najpewniej jest uszkodzony/nieobsługiwany.
            if self.duration <= 0.0 and (time.time() - self.load_time) < 3.0:
                self.bad_file = True
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
        if not self.playlist:
            return
        file_name = self.playlist[self.current_idx]
        mp3_path = os.path.join(self.dir, file_name)
        
        self.metadata = {'artist': 'Nieznany', 'album': 'Nieznany'}
        self.ascii_art = []
        uslt_lyrics = []
        self.bad_file = False

        # Szybka wstępna weryfikacja - czy plik w ogóle da się otworzyć i coś zawiera
        try:
            if os.path.getsize(mp3_path) == 0:
                raise ValueError("Pusty plik")
            with open(mp3_path, 'rb') as f:
                f.read(4)
        except (OSError, ValueError):
            self.bad_file = True

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
                with Image.open(io.BytesIO(apic[0].data)) as raw_img:
                    img = raw_img.convert('RGB').resize((24, 10))
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
        except (OSError, ValueError, KeyError, TypeError):
            # Obejmuje typowe błędy uszkodzonych/nietypowych tagów ID3 oraz
            # niepoprawnych danych obrazka (mutagen/Pillow rzucają różne wyjątki
            # w zależności od tego, co dokładnie jest nie tak z plikiem).
            pass
        
        if uslt_lyrics:
            self.lyrics = uslt_lyrics
        else:
            lrc_path = os.path.splitext(mp3_path)[0] + ".lrc"
            self.lyrics = self.parse_lrc(lrc_path)
        
        self.time_pos = 0.0
        self.duration = 0.0
        self.needs_next = False
        self.load_time = time.time()

        if self.bad_file:
            # Plik wygląda na nieodtwarzalny - nie próbuj go nawet ładować do mpv,
            # zasygnalizuj natychmiastowe przejście dalej.
            self.needs_next = True
            return

        try:
            self.player.play(mp3_path)
        except Exception:
            self.bad_file = True
            self.needs_next = True

    def refill_shuffle_bag(self):
        """Losuje nową kolejność odtwarzania (pomijając aktualnie grany utwór, o ile to możliwe)."""
        indices = list(range(len(self.playlist)))
        # Dla playlisty z 1 utworem usunięcie bieżącego indeksu zostawiłoby pusty
        # worek i wywołałoby IndexError przy najbliższym .pop() - w takim wypadku
        # pozwalamy na odtworzenie tego samego utworu zamiast wywalać program.
        if len(indices) > 1 and self.current_idx in indices:
            indices.remove(self.current_idx)
        random.shuffle(indices)
        self.shuffle_bag = indices

    def advance_track(self, direction=1):
        """Ręczne lub automatyczne przejście do kolejnego/poprzedniego utworu."""
        if not self.playlist:
            return
        if self.shuffle:
            if direction > 0:
                self.history.append(self.current_idx)
                if len(self.history) > 1000:
                    self.history.pop(0)
                if not self.shuffle_bag:
                    self.refill_shuffle_bag()
                self.current_idx = self.shuffle_bag.pop()
            else:
                if self.history:
                    self.current_idx = self.history.pop()
                else:
                    if not self.shuffle_bag:
                        self.refill_shuffle_bag()
                    self.current_idx = self.shuffle_bag.pop()
        else:
            self.current_idx = (self.current_idx + direction) % len(self.playlist)
        self.load_track()

    def next_track(self):
        self.advance_track(1)

    def prev_track(self):
        self.advance_track(-1)

    def toggle_shuffle(self):
        self.shuffle = not self.shuffle
        self.shuffle_bag = []
        self.history = []

    def cycle_repeat(self):
        self.repeat_mode = (self.repeat_mode + 1) % 3

    def on_track_end(self):
        """Wywoływane, gdy bieżący utwór zakończył odtwarzanie (naturalnie lub przez błąd)."""
        self.needs_next = False

        if self.bad_file:
            self.bad_file = False
            if not self.skip_bad_files:
                # Zatrzymaj na miejscu i pokaż informację o błędzie zamiast pomijać
                self.player.pause = True
                return
            self.failed_attempts += 1
            if self.failed_attempts >= max(1, len(self.playlist)):
                # Cała playlista wygląda na uszkodzoną - przerwij, by nie kręcić się w kółko
                self.failed_attempts = 0
                self.player.pause = True
                return
            self.advance_track(1)
            return

        self.failed_attempts = 0

        if not self.auto_next:
            return

        if self.repeat_mode == REPEAT_ONE:
            self.load_track()
            return

        if self.repeat_mode == REPEAT_OFF:
            if self.shuffle:
                playlist_exhausted = (not self.shuffle_bag) and (len(self.history) >= len(self.playlist) - 1)
                if playlist_exhausted:
                    self.player.pause = True
                    return
            else:
                if self.current_idx == len(self.playlist) - 1:
                    self.player.pause = True
                    return

        self.advance_track(1)

    def format_time(self, seconds):
        if seconds < 0: seconds = 0
        m, s = divmod(int(seconds), 60)
        return f"{m:02d}:{s:02d}"

    def run(self):
        while True:
            # Obsługa zakończenia utworu (naturalna, błąd pliku, powtarzanie, shuffle...)
            if self.needs_next:
                self.on_track_end()

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
            title_str = title_str[:max(0, width - 1)]  # bardzo długie nazwy plików nie mogą wywrócić renderowania
            try:
                self.stdscr.addstr(0, max(0, width//2 - len(title_str)//2), title_str, curses.color_pair(3) | curses.A_BOLD)
            except curses.error:
                pass

            time_str = f" {self.format_time(self.time_pos)} / {self.format_time(self.duration)} "
            bar_width = width - len(time_str) - 4
            if bar_width > 0:
                progress = min(1.0, max(0.0, self.time_pos / self.duration)) if self.duration > 0 else 0.0
                filled = int(bar_width * progress)
                bar = "[" + "=" * filled + ">" + " " * (bar_width - filled - 1) + "]"
                try:
                    self.stdscr.addstr(2, 2, bar + time_str, curses.color_pair(2))
                except curses.error:
                    pass

            vol = getattr(self.player, 'volume', 100.0)
            mute = getattr(self.player, 'mute', False)
            pause = getattr(self.player, 'pause', False)
            
            vol_str = f"Głośność: {'WYCISZONY' if mute else f'{int(vol)}%'}"
            state_str = "PAUZA" if pause else "ODTWARZANIE"
            auto_str = "AUTO-NEXT: WŁ" if self.auto_next else "AUTO-NEXT: WYŁ"
            try:
                self.stdscr.addstr(3, 2, f"{vol_str} | {state_str} | {auto_str}"[:max(0, width - 4)], curses.color_pair(2) | curses.A_BOLD)
            except curses.error:
                pass

            # --- DRUGI PASEK STATUSU: Shuffle / Powtarzanie / Auto-pomijanie błędów ---
            shuffle_str = f"SHUFFLE: {'WŁ' if self.shuffle else 'WYŁ'}"
            repeat_str = f"POWTARZAJ: {REPEAT_LABELS[self.repeat_mode]}"
            skip_str = f"POMIJANIE BŁĘDÓW: {'WŁ' if self.skip_bad_files else 'WYŁ'}"
            status2 = f"{shuffle_str} | {repeat_str} | {skip_str}"
            try:
                self.stdscr.addstr(4, 2, status2[:max(0, width - 4)], curses.color_pair(3))
            except curses.error:
                pass

            self.stdscr.hline(5, 0, curses.ACS_HLINE, width)

            # --- PANEL INFORMACYJNY: Autor, Album i Miniaturka Kolorowego ASCII ---
            meta_str = f"Autor: {self.metadata['artist']} | Album: {self.metadata['album']}"
            if 6 < height - 2:
                self.stdscr.addstr(6, 2, meta_str[:width-4], curses.color_pair(3) | curses.A_BOLD)
            
            for i, line_data in enumerate(self.ascii_art):
                row = 7 + i
                if row < height - 2:
                    for j, (char, color_idx) in enumerate(line_data):
                        try:
                            self.stdscr.addstr(row, 2 + j, char, curses.color_pair(color_idx))
                        except curses.error:
                            pass # Zabezpieczenie przy rysowaniu na krawędziach

            # --- ŚRODKOWY PANEL: Wyśrodkowane i przygaszane napisy ---
            top_margin = 7 + len(self.ascii_art) # Wyliczenie marginesu tak, aby nie nachodziło na obraz

            if self.bad_file:
                msg = "BŁĄD: NIE MOŻNA ODTWORZYĆ PLIKU"
                self.stdscr.attron(curses.color_pair(4) | curses.A_BOLD)
                try:
                    self.stdscr.addstr(height // 2, max(0, width // 2 - len(msg) // 2), msg)
                except curses.error:
                    pass
                self.stdscr.attroff(curses.color_pair(4) | curses.A_BOLD)
            elif not self.lyrics:
                msg = "BRAK TEKSTU"
                self.stdscr.attron(curses.color_pair(4) | curses.A_BOLD)
                self.stdscr.addstr(height // 2, max(0, width // 2 - len(msg) // 2), msg)
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
                visible_lines = max(3, (height - center_y - 2))

                start_idx = max(0, current_index - visible_lines)
                end_idx = min(len(self.lyrics), current_index + visible_lines + 1)

                # Zanim padnie pierwsza linijka tekstu (current_index == -1), traktujemy
                # pozycję "tuż przed start_idx" jako punkt odniesienia, żeby nadchodzące
                # wersy pojawiały się od razu pod środkiem, zamiast dokładnie na środku.
                anchor = current_index if current_index >= 0 else start_idx - 1
                row_y = center_y - (anchor - start_idx)

                for i in range(start_idx, end_idx):
                    if top_margin <= row_y < height - 2:
                        text = self.lyrics[i][1]
                        
                        if i == current_index:
                            # Mocno wyróżniony aktualny wers z ramkami - symulacja większego rozmiaru
                            highlighted_text = f"► {text} ◄"
                            col_x = max(0, width // 2 - len(highlighted_text) // 2)
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
            full_help_str = " ←/→:Przewijaj | ↑/↓:Głośność | Spacja:Pauza | m:Wycisz | a:Auto-next | s:Shuffle | r:Powtarzaj | b:Auto-pomijanie | n/p:Nast/Poprz | q:Wyjście "
            short_help_str = " Spacja:Pauza | ↑/↓:Vol | n/p:Utwór | s:Shuffle | r:Powtarzaj | q:Wyjście "
            help_str = full_help_str if width >= 100 else short_help_str
            help_str = help_str[:max(0, width - 1)]
            try:
                self.stdscr.addstr(height - 1, max(0, width//2 - len(help_str)//2), help_str, curses.color_pair(3) | curses.A_REVERSE)
            except curses.error:
                pass

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
            elif c == ord('a'):
                self.auto_next = not self.auto_next
                self.needs_next = False
            elif c == ord('s'):
                self.toggle_shuffle()
            elif c == ord('r'):
                self.cycle_repeat()
            elif c == ord('b'):
                self.skip_bad_files = not self.skip_bad_files
            elif c in [curses.KEY_HOME, 262]:
                self.player.time_pos = 0.0
            elif c in [curses.KEY_END, 360]:
                if self.duration: self.player.time_pos = max(0.0, self.duration - 1.0)
            elif c == ord('n'):
                self.needs_next = False
                self.bad_file = False
                self.next_track()
            elif c == ord('p'):
                self.needs_next = False
                self.bad_file = False
                self.prev_track()

            time.sleep(0.05)

        self.player.terminate()

def main(stdscr, target_path):
    # curses.wrapper zawsze poprawnie przywróci terminal, ale samo w sobie nie
    # przekazuje treści wyjątku dalej - łapiemy go tutaj, żeby użytkownik dostał
    # czytelny komunikat zamiast surowego tracebacku na (już naprawionym) terminalu.
    try:
        MpvLrcPlayer(stdscr, target_path).run()
    except Exception as e:
        return str(e)
    return None

if __name__ == "__main__":
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