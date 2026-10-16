MODBUS METEO -> LEMMY
Wersja przenośna, przygotowana do publikacji kodu źródłowego

CO ROBI PROGRAM
Odczytuje temperaturę, wilgotność i ciśnienie z urządzenia Modbus TCP.
Przelicza każdy rejestr według osobnego mnożnika, zapisuje historię w SQLite,
tworzy trzy wykresy bieżącego miesiąca i aktualizuje jeden wpis Lemmy.
Wpis zawiera wartości, krótki status stacji, czas pomiaru i wykresy.
Użytkownik może zachować stały opis pod wykresami, np. parametry czujników.

Wszystkie adresy urządzeń, adres instancji i dane konta podaje użytkownik.
Szablon config.example.json nie zawiera danych wdrożenia ani sekretów.
Konfiguracja rzeczywista config.json jest ignorowana przez Git.

WYMAGANIA I ZAKRES
- Debian/Linux z Pythonem 3.11 lub nowszym; sprawdzono na Debianie 12 / 3.11.2.
- Pakiety systemowe: python3, python3-venv, cron, ca-certificates; opcjonalnie mc.
- Dostęp sieciowy do urządzenia Modbus i HTTPS do własnej instancji Lemmy.
- Aktywne konto Lemmy mogące publikować w wybranej społeczności.
- Przypinanie wymaga uprawnień moderatora społeczności lub administratora.
- API Lemmy v3, oparte na działającym wdrożeniu 0.19.11. API v4 nie jest
  zaimplementowane; przed inną wersją serwera sprawdź zgodność.
- Instancja musi pozwalać temu kontu wysyłać obrazy przez /pictrs/image.
- Obsługiwane są pojedyncze rejestry 16-bitowe int16/uint16, FC03/FC04.
  Float32, pary rejestrów, kolejność słów i inne jednostki wymagają rozbudowy.
- Program wykonuje wyłącznie odczyt Modbus, nie zapisuje rejestrów.
- Windows służy do przechowywania/edycji plików; uruchomienie wymaga Linuxa
  (blokady fcntl, CRON). Nie potrzeba Dockera ani serwera WWW dla klienta.

INSTALACJA KROK PO KROKU

1. Na docelowym Debianie przygotuj pakiety:
   sudo apt-get update
   sudo apt-get install python3 python3-venv cron ca-certificates mc
   Nie jest potrzebny restart serwera.

2. Skopiuj zawartość tego katalogu do wybranego folderu, np. ~/meteo.
   Dalsze polecenia wykonuj jako zwykły użytkownik, właściciel tego folderu:
   cd ~/meteo
   sh install.sh
   Instalator tworzy .venv, instaluje zależności, tworzy katalogi robocze
   i config.json, jeśli jeszcze nie istnieje. Nie włącza CRON-a ani publikacji.

3. Uzupełnij konfigurację:
   mcedit config.json
   Wpisz host/port/unit_id, adres każdego rejestru i mnożnik; sprawdź signed.
   Ustaw własną strefę czasową IANA. Szczegóły w KONFIGURACJA.txt.
   Na początku pozostaw lemmy.enabled=false.
   chmod 600 config.json
   .venv/bin/python settings.py
   To wyłącznie walidacja składni i pól; bez połączeń sieciowych.

4. Uruchom testy i rzeczywisty odczyt:
   .venv/bin/python -m unittest discover -v
   .venv/bin/python meteo.py
   .venv/bin/python charts.py
   Testy wykorzystują fikcyjne dane i mock API, nie kontaktują się z czujnikami
   ani instancją. Odczyt meteo.py kontaktuje się z urządzeniem i dopisuje próbę
   do historii. Obejrzyj data/status.json oraz trzy PNG w wykresy/.

5. Przygotuj konto i społeczność w Lemmy.
   Zwykłe hasło tego konta jest używane do uzyskania JWT przez API.
   Hasło aplikacji Google/SMTP nie jest hasłem konta Lemmy.
   Program nie tworzy użytkowników, nie zmienia bazy Lemmy ani uprawnień.
   Jeżeli konto wymaga 2FA/TOTP, ten klient nie obsługuje formularza TOTP.
   W config.json uzupełnij sekcję lemmy: instance (pełny adres HTTPS),
   username, password, community_id, title, heading i opcjonalne przypięcie.
   Community_id musi być lokalnym ID na docelowej instancji. Możesz uzyskać
   je z JSON jej API GET /api/v3/community?name=NAZWA_SPOLECZNOSCI:
   pole community_view.community.id. Nie myl nazwy widocznej z identyfikatorem.

6. Wybierz nowy lub istniejący wpis.
   Dla nowego pozostaw post_id=null. Opcjonalnie:
   cp static.example.txt static.txt
   mcedit static.txt
   Wpisz stały opis czujników. Będzie dołączony tylko podczas tworzenia wpisu.
   Późniejsze poprawki stałej części wykonuj już w edytorze Lemmy.
   Dla istniejącego własnego wpisu ustaw post_id i umieść w jego treści:

   [meteo-start]: #

   Tutaj program wstawi wyniki i wykresy.

   [meteo-end]: #

   Tutaj możesz dopisać stały opis czujników.

   Oba znaczniki muszą wystąpić dokładnie raz, w tej kolejności i jako
   osobne wiersze. Puste wiersze są istotne dla renderowania Markdown.
   Program zachowuje treść przed i po sekcji. Przy braku znaczników odmawia
   edycji. Nie stosuj widocznych komentarzy HTML jako nowych znaczników.

7. Włącz lemmy.enabled=true. Wykonaj świadomie pierwszą publikację:
   .venv/bin/python settings.py
   .venv/bin/python run_cycle.py
   Polecenie odczyta pomiar, utworzy wykresy i utworzy/zaktualizuje wpis.
   Adres aktualizowanego wpisu znajdziesz w logs/meteo.log.
   Stan i ID wpisu zostaną zapisane w data/lemmy-state.json.
   Zweryfikuj wygląd wpisu oraz uprawnienia do przypięcia, jeśli je włączono.

8. Dopiero po udanym teście zainstaluj harmonogram:
   .venv/bin/python install_cron.py
   crontab -l
   systemctl is-active cron
   Jeśli usługa jest wyłączona: sudo systemctl enable --now cron
   Skrypt dodaje zadanie co pełną godzinę dla bieżącego użytkownika,
   z bezwzględną ścieżką do tej instalacji. Zachowuje inne zadania i zapisuje
   kopię poprzedniego crontab w data/. Zastępuje linię # meteo-collector:
   zakłada jedną stację dla tego użytkownika systemowego.

JAK DZIAŁA CYKL
run_cycle.py -> meteo.py -> SQLite/status -> charts.py -> publish_lemmy.py.
Odczyty trzech rejestrów są osobnymi zapytaniami, dzięki czemu mogą być
oddalone i nie trzeba czytać niedostępnych rejestrów między nimi. Nie jest
to atomowa próbka sprzętowa; wartości powstają w krótkich odstępach czasu.
Przy niepowodzeniu dowolnego rejestru cała próba jest błędna i powtarzana.
Błędy zapisywane są jako NULL, nie jako zerowe pomiary. Program pokazuje
ostatnie dobre wartości i ich datę, jeśli aktualny odczyt zawiedzie.

Lemmy otrzymuje tekst Markdown, a wykresy pliki PNG (16:9, 1680x945).
Status zielony oznacza poprawny, wystarczająco świeży odczyt wszystkich
parametrów w chwili publikacji. Nie stanowi pełnej diagnostyki sprzętu.
Gdy zatrzyma się cały program, internet lub Lemmy, post nie zmieni statusu
samodzielnie: zostanie stara data. Niezależny alarm wymaga zewnętrznego nadzoru.

Stan publikacji zapobiega tworzeniu nowego posta co godzinę. Po niepewnym
wyniku tworzenia program szuka własnego wpisu o tym samym tytule, społeczności
i znacznikach w ostatnich 50 wpisach autora; jeśli wynik jest niejednoznaczny,
odmawia tworzenia kolejnego. Administrator musi wskazać właściwy post_id.
Zmiana konta/instancji/społeczności przy starym stanie jest blokowana.

Wykresy wybierają miesiąc według timezone. Baza przechowuje UTC. Przy zmianie
miesiąca wykresy zaczynają się od nowa, ale historyczne pomiary zostają w bazie.
Braki i zbyt długie odstępy pomiarów przerywają linie. Obrazy wysyłane są na
instancję Lemmy. Starych obrazów program automatycznie nie usuwa; trzeba
uwzględnić miejsce w pict-rs. Historia uploadów zawiera tokeny do usuwania.

OBSŁUGA I ZMIANY
- Pełny cykl ręcznie: .venv/bin/python run_cycle.py
- Sam pomiar: .venv/bin/python meteo.py
- Bieżące wykresy: .venv/bin/python charts.py
- Archiwalny miesiąc: .venv/bin/python charts.py --month RRRR-MM
  To nadpisuje lokalne PNG, więc przed publikacją przywróć bieżące wykresy.
- Sama publikacja: .venv/bin/python publish_lemmy.py
  Wymaga istniejących, spójnych plików pomiarów i wykresów. Zwykle używaj cyklu.
- Log: tail -n 60 logs/meteo.log
- CRON: EDITOR=mcedit crontab -e
- Wyłączenie zadania: .venv/bin/python install_cron.py --remove
  Nie usuwa plików ani wpisu. Nie uruchamiaj z sudo.
- Przerwa tylko w publikowaniu: lemmy.enabled=false; pomiary i wykresy zostają.
- Inna częstotliwość: edytuj crontab, stale_after_minutes i lemmy.update_note.
  Ponowne install_cron.py przywraca harmonogram godzinowy.
- Tytuł jest używany przy tworzeniu/szukaniu wpisu; zmiana title w config
  nie przemianuje istniejącego posta. Zrób to w Lemmy i uaktualnij config.

PLIKI
settings.py           wczytanie i kontrola konfiguracji
config.example.json   pusty szablon ustawień, przeznaczony do publikacji
config.json           dane użytkownika, powstaje przy instalacji, NIE publikuj
meteo.py              Modbus, skalowanie, SQLite, status
charts.py             trzy wykresy i manifest zgodności danych
publish_lemmy.py      JWT, przesyłanie obrazów, edycja jednego wpisu
run_cycle.py          kolejność i blokada cyklu
install.sh            venv, zależności, katalogi; bez CRON-a
install_cron.py       harmonogram i kopia poprzedniego crontab
static.example.txt    wzór stałej sekcji posta
static.txt            własny opis, używany przy pierwszym tworzeniu
requirements.lock.txt zamrożone wersje bibliotek wykresów
test_*.py             testy bez korzystania z serwerów produkcyjnych
data/                 SQLite, status, JWT, ID wpisu, historia uploadów
wykresy/              PNG i manifest.json
logs/                 log aplikacji i wyjście CRON-a
.cache/, .venv/, tmp/  lokalne cache, środowisko i pliki pomocnicze

PRZENIESIENIE NA KOLEJNY SERWER
1. Wyłącz stare zadanie CRON i poczekaj na zakończenie aktualnego cyklu.
2. Skopiuj kod, config.json, static.txt (jeśli istnieje), cały data/ oraz
   opcjonalnie wykresy/ i logs/. Zatrzymanej aplikacji nie uruchamiaj podczas
   kopiowania. Kopiując bazę na żywo użyj sqlite3.Connection.backup(), nie
   kopiuj samego pliku sqlite3 z pominięciem aktywnego WAL.
3. Na nowym serwerze wykonaj sh install.sh. Zachowuje istniejący config.json.
4. Sprawdź właściciela plików i chmod 600 config.json; folder data powinien
   być prywatny. Uruchom test, jeden pełny cykl i dopiero potem nowy CRON.
5. Nie uruchamiaj dwóch serwerów publikujących do jednego wpisu równocześnie.
   Dla innej instancji/konta odłóż stare pliki data/lemmy-* do prywatnego backupu,
   uzupełnij nowe ustawienia i post_id. Nie mieszaj stanów dwóch instalacji.

PRZED PUBLIKACJĄ W GITHUBIE
Publikuj zawartość tylko tego katalogu. Nie dołączaj konfiguracji rzeczywistej,
SQLite, tokenów, logów, wykresów, archiwów ani plików prywatnych z katalogu
nadrzędnego. .gitignore ogranicza przypadkowe dodanie, ale nie usuwa sekretów
z istniejącej historii Git. Przed git add/commit sprawdź git status i diff.
Projekt jest udostępniany na licencji GNU GPLv3 (GPL-3.0-only). Pełny tekst licencji znajduje się w pliku LICENSE.

Wersja nie instaluje SMTP ani hooków YunoHost — to konfiguracja instancji,
a klient korzysta wyłącznie z Modbus, SQLite i uwierzytelnionego API Lemmy.
