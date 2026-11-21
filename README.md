# War Thunder BlackBox

Kişisel War Thunder maç analiz aracı. Önce hava muharebeleri (Air RB), maç sonrası analiz.

Veri kaynağı yalnızca oyunun kendi yerel telemetri arayüzü (`http://127.0.0.1:8111`).
Bellek okuma, enjeksiyon veya oyun dosyasına müdahale **yoktur**.

Gereksinim: Python 3.10+ (ek paket gerekmez).

## 1. Maçları kaydet

Oyundan önce başlat, açık bırak. Maçlar otomatik algılanır ve `recordings/` klasörüne kaydedilir:
```powershell
python recorder/record.py
```
Hangarda API'yi hızlıca kontrol etmek için: `python recorder/record.py --probe`
Tek bir kaydın ham raporu için: `python recorder/inspect_session.py`

## 2. Analiz et

İlk seferde oyun içi adını kaydet:
```powershell
python -m blackbox setup ENDERKING_tr
```
Yeni kayıtları veritabanına aktar (`blackbox.db`):
```powershell
python -m blackbox import
```
İstatistikler:
```powershell
python -m blackbox stats
python -m blackbox stats --vehicle fa_18c_late --last 20
python -m blackbox matches
python -m blackbox match 200407
```
Haritalar: oyun harita adını vermediği için her haritaya bir anahtar atanır. Bir kez isim verirsin:
```powershell
python -m blackbox maps
python -m blackbox name-map b4037ac4 "Sinai"
```
Tanınmayan kill feed satırları (ayrıştırıcıyı geliştirmek için): `python -m blackbox unknown`

Analiz kodu güncellendiğinde `import` eski maçları otomatik yeniden işler; `--force` hepsini zorla yeniden işler.

## Bilinen sınırlamalar
- API'de füze/RWR verisi ve kill mesajlarında silah bilgisi yok; davranış analizi tahmine dayalıdır.
- "En yakın düşman" yalnızca minimapte görünen (tespit edilmiş) düşmanları kapsar.
- Düştükten sonra maçtan çıkarsan maç sonucu bilinemez (`unknown`).

## Geliştirme
```powershell
python -m unittest discover tests
python dev/fake_wt_server.py --port 8112
python recorder/record.py --url http://127.0.0.1:8112
```
