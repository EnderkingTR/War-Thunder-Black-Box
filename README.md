# War Thunder BlackBox

Kişisel War Thunder maç analiz aracı. Önce hava muharebeleri (Air RB), maç sonrası analiz.

Veri kaynağı yalnızca oyunun kendi yerel telemetri arayüzü (`http://127.0.0.1:8111`).
Bellek okuma, enjeksiyon veya oyun dosyasına müdahale **yoktur**.

## Durum: Faz 1 – Veri keşfi

Amaç: API'nin gerçek bir maçta ne verdiğini görmek ve analiz tasarımını buna göre yapmak.

### Gereksinim
Python 3.10+ (ek paket gerekmez).

### Test adımları

1. **Hangarda hızlı kontrol.** Oyun açıkken çalıştır:
   ```powershell
   python recorder/record.py --probe
   ```
   Çıktı `recordings/_probe/` klasörüne kaydedilir.

2. **Maç kaydı.** Maçtan önce başlat, açık bırak:
   ```powershell
   python recorder/record.py
   ```
   Maç başlayınca kayıt otomatik başlar, bitince `recordings/<tarih_saat>/` klasörüne kaydedilir.
   Birden fazla maç oynayabilirsin. Kapatmak için `Ctrl+C`.

3. **Rapor.** En son kaydı incelemek için:
   ```powershell
   python recorder/inspect_session.py
   ```
   Rapor `report.txt` olarak kaydın klasörüne yazılır.

### Geliştirme
`dev/fake_wt_server.py` oyunu taklit eden sahte bir sunucudur. Oyun açık olmadan test etmek için kullanılır:
```powershell
python dev/fake_wt_server.py --port 8112
python recorder/record.py --url http://127.0.0.1:8112
```
