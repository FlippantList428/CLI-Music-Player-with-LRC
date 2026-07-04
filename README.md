# MPV CLI LRC Player

Ten projekt to lekki odtwarzacz muzyki działający całkowicie w terminalu, wyposażony w funkcję wyświetlania zsynchronizowanego tekstu utworu z plików `.lrc`. Został napisany w języku Python, wykorzystując interfejs `curses` do renderowania grafiki w konsoli oraz silnik `mpv` do obsługi dźwięku.

## 📦 Wymagania i zależności

Do poprawnego działania skryptu niezbędne są:

* **Python 3** (wykorzystuje wbudowane moduły: `sys`, `os`, `re`, `time`, `curses`)


* **mpv** (systemowy odtwarzacz multimedialny)
* **python-mpv** (Pythonowe dowiązanie do biblioteki mpv)

### Instalacja w różnych dystrybucjach Linuxa

Aby zainstalować potrzebne pakiety, użyj polecenia odpowiedniego dla Twojego systemu:

**Arch Linux / Manjaro**

```bash
sudo pacman -S mpv python-mpv

```

**Ubuntu / Pop!_OS**

```bash
sudo apt update
sudo apt install mpv python3-mpv

```

**Linux Mint / Debian**

```bash
sudo apt update
sudo apt install mpv python3-mpv

```

**Fedora**

```bash
sudo dnf install mpv python3-mpv

```

> **Wskazówka:** Jeśli Twoja dystrybucja (np. starsza wersja Ubuntu) nie posiada w repozytorium pakietu `python3-mpv`, zainstaluj najpierw systemowy odtwarzacz `mpv`, a wtyczkę dla Pythona pobierz za pomocą pip:
> `sudo apt install mpv && pip install python-mpv`

## 🚀 Uruchamianie i Użycie

Program ładuje pliki `.mp3` i dopasowuje do nich pliki tekstowe `.lrc` o identycznej nazwie. Odtwarzacz zignoruje brak pliku `.lrc`, wyświetlając odpowiedni komunikat i po prostu odtworzy muzykę.

Uruchom odtwarzacz na jeden z poniższych sposobów:

**1. Uruchomienie wybranego utworu:**

```bash
python cli_player.py nazwa_pliku.mp3

```

**2. Uruchomienie całego folderu z muzyką:**

```bash
python cli_player.py /ścieżka/do/katalogu/z/muzyką

```

(Program automatycznie stworzy playlistę ze wszystkich plików MP3 w tym folderze i zacznie grać).

**3. Uruchomienie w bieżącym katalogu (przy odpowiedniej konfiguracji kodu):**

```bash
python cli_player.py

```

## ⌨️ Sterowanie (Klawiszologia)

Gdy odtwarzacz jest uruchomiony w terminalu, obsługujesz go następującymi klawiszami:

* **`Spacja`** – Pauza / Wznowienie odtwarzania


* **`←` / `→**` – Przewijanie utworu (skok o 5 sekund wstecz/w przód)


* **`↑` / `↓**` – Regulacja głośności (+/- 5%)


* **`m`** – Całkowite wyciszenie / odciszenie dźwięku


* **`n`** – Przeskocz do następnego utworu na liście


* **`p`** – Wróć do poprzedniego utworu na liście


* **`Home`** – Przeskocz na sam początek utworu


* **`End`** – Przeskocz tuż przed koniec utworu


* **`q`** – Zamknięcie programu