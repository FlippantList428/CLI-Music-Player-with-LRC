# MPV CLI LRC Player

Ten projekt to lekki odtwarzacz muzyki działający całkowicie w terminalu, wyposażony w funkcję wyświetlania zsynchronizowanego tekstu utworu z plików `.lrc`. Został napisany w języku Python, wykorzystując interfejs `curses` do renderowania grafiki w konsoli oraz silnik `mpv` do obsługi dźwięku.

## 📦 Wymagania i zależności

Do poprawnego działania skryptu niezbędne są:

* **Python 3** (wraz z wbudowanymi modułami: `sys`, `os`, `re`, `time`, `curses`, `io`)


* **Biblioteki zewnętrzne**: `mpv`, `mutagen` (do obsługi metadanych ID3) oraz `Pillow` (do generowania ASCII artu)

### Instalacja w różnych dystrybucjach Linuxa

Aby zainstalować potrzebne pakiety, użyj polecenia odpowiedniego dla Twojego systemu.

**Arch Linux / Manjaro**

```bash
sudo pacman -S mpv python-mpv python-mutagen python-pillow

```

**Ubuntu / Pop!_OS / Linux Mint / Debian**

```bash
sudo apt update
sudo apt install mpv python3-mpv python3-mutagen python3-pil

```

**Fedora**

```bash
sudo dnf install mpv python3-mpv python3-mutagen python3-pillow

```

> **Wskazówka:** Jeśli Twój system nie posiada w repozytorium pakietu `python-mpv` lub `python-pillow`, możesz je zainstalować za pomocą pip (wymaga `pip`):
> `pip install python-mpv mutagen pillow`

## 🚀 Uruchamianie i Użycie

Program automatycznie pobiera metadane (Autor, Album) oraz wbudowany tekst (`USLT`) z pliku `.mp3` lub wczytuje zewnętrzny plik `.lrc` o tej samej nazwie.

Uruchom odtwarzacz na jeden z poniższych sposobów:

**1. Uruchomienie wybranego utworu:**

```bash
python cli_player.py nazwa_pliku.mp3

```

**2. Uruchomienie całego folderu z muzyką:**

```bash
python cli_player.py /ścieżka/do/katalogu/z/muzyką

```

(Program automatycznie stworzy playlistę ze wszystkich plików MP3 w tym folderze).

**3. Uruchomienie w bieżącym katalogu:**

```bash
python cli_player.py

```

## ⌨️ Sterowanie (Klawiszologia)

Gdy odtwarzacz jest uruchomiony w terminalu, obsługujesz go następującymi klawiszami:

* **`Spacja`** – Pauza / Wznowienie odtwarzania


* **`←` / `→**` – Przewijanie utworu (skok o 5 sekund wstecz/w przód)


* **`↑` / `↓**` – Regulacja głośności (+/- 5%)


* **`m`** – Całkowite wyciszenie / odciszenie dźwięku


* **`a`** – Włącz/wyłącz automatyczne przechodzenie do następnego utworu po zakończeniu bieżącego


* **`s`** – Włącz/wyłącz odtwarzanie losowe (shuffle)


* **`r`** – Przełącz tryb powtarzania: WYŁ → WSZYSTKO → JEDEN → WYŁ


* **`b`** – Włącz/wyłącz automatyczne pomijanie uszkodzonych/nieodtwarzalnych plików


* **`n`** – Przeskocz do następnego utworu na liście


* **`p`** – Wróć do poprzedniego utworu na liście


* **`Home`** – Przeskocz na sam początek utworu


* **`End`** – Przeskocz tuż przed koniec utworu


* **`q`** – Zamknięcie programu

### 🔁 Szczegóły nowych trybów

* **Shuffle (`s`)** – utwory są losowane bez powtórzeń, dopóki cała playlista nie zostanie odtworzona (dopiero wtedy losowanie zaczyna się od nowa). Klawisz `p` w tym trybie cofa Cię do faktycznie poprzednio odtworzonego utworu (historia), a nie do poprzedniego indeksu na liście.
* **Powtarzanie (`r`)**:
  * `WYŁ` – po ostatnim utworze (lub po przejściu całej losowej puli w trybie shuffle) odtwarzanie zatrzymuje się.
  * `WSZYSTKO` – po ostatnim utworze playlista zaczyna się od nowa (domyślne zachowanie).
  * `JEDEN` – bieżący utwór odtwarza się w kółko.
  * Powyższe tryby działają tylko wtedy, gdy `AUTO-NEXT` jest włączone; ręczne `n`/`p` zawsze przechodzą do innego utworu.
* **Auto-pomijanie błędów (`b`)** – gdy włączone (domyślnie), plik pusty, uszkodzony lub taki, którego mpv nie potrafi odtworzyć, jest automatycznie pomijany, a odtwarzacz przechodzi dalej. Jeśli wyłączysz tę opcję, odtwarzacz zatrzyma się na uszkodzonym pliku i pokaże komunikat o błędzie zamiast go pomijać.