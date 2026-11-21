# War Thunder BlackBox

Kişisel War Thunder maç analiz aracı. Önce hava muharebeleri (Air RB), maç sonrası analiz.

Yalnızca oyunun kendi ürettiği verileri okur: yerel telemetri arayüzü (`127.0.0.1:8111`),
diskteki replay dosyaları (`.wrpl`) ve hangarda kopyaladığın savaş sonucu metinleri.
Bellek okuma, enjeksiyon, oyun dosyasına müdahale veya şifre çözme **yoktur**.

Gereksinim: Python 3.14+ (replay sıkıştırması için standart kütüphanedeki `compression.zstd`). Ek paket gerekmez.

## Üç veri kaynağı

| Kaynak | Ne verir | Nasıl gelir |
|---|---|---|
| Telemetri (8111) | Uçuş verisi: irtifa, hız, G, konum, minimapteki düşmanlar, kill feed | `recorder/record.py` açıkken otomatik |
| Replay (`.wrpl`) | Harita, kim kimi **hangi silahla** düşürdü, lobideki 32 oyuncunun skor/K/D/füzeden kaçış | Oyun ayarında replay otomatik kaydı açık olmalı |
| Sonuç metni | Zafer/yenilgi, SL/RP, tamir, aktivite | Hangardaki savaş sonucu bildiriminde "kopyala"ya bas; recorder açıksa panodan otomatik kaydedilir |

Üçü oturum kimliği (`Oturum: ...`) üzerinden aynı maça bağlanır.

## Kullanım

İlk seferde oyun içi adını kaydet (replay klasörün farklıysa `--replay-dir` ekle):
```powershell
python -m blackbox setup ENDERKING_tr
```

Oynamadan önce recorder'ı başlat (telemetri + pano izleyici):
```powershell
python recorder/record.py
```

Oynadıktan sonra içe aktar ve bak:
```powershell
python -m blackbox import
python -m blackbox stats
python -m blackbox battles --last 10
python -m blackbox battle 72c412c10016f0ec --lobby
```

### Web arayüzü
```powershell
python -m blackbox web
```
Tarayıcıda `http://127.0.0.1:8765` açılır (yalnızca bu bilgisayardan erişilir). Sayfalar: Özet, Maçlar
(tıklayınca maç detayı: zaman çizelgesi, uçuş profili, rota, ödüller, takımlar), Beceri, Silahlar, Haritalar,
Araçlar, Grind. Sağ üstteki "İçe aktar" yeni replay/kayıtları alır; dört renk teması vardır.
`--port 9000` ve `--no-browser` seçenekleri var.

**Beceri sayfası** tahmini bir analizdir: replay'lerden seni neyin düşürdüğünü (radar/IR füze, top, SAM, kaza)
aynı maçlardaki lobiyle karşılaştırır; telemetrili maçlarda her ölümün son 15 saniyesine bakar (en yakın görünen
düşmana göre notch / soğuk kaçış / tehdide doğru uçuş, radar irtifasıyla multipath, G, hız ve irtifa değişimi).
Oyun füze atışını ve RWR'ı vermediği için tehdit, atan uçak değil en yakın görünen düşmandır.
Kara filtresinde Beceri sayfası seni düşüren araç türünü (tank, SPAA, uçak, helikopter) ve mühimmat türünü
lobiyle karşılaştırır; kara maçlarında kill = kara + hava kill. Yeniden doğan araçlar replay'de yeni kimlik
aldığı için ölümlerin bir kısmı araç türüne eşlenemeyebilir; sayfa kaçının eşlendiğini gösterir.

**Üs bombalama** ton hasarına göre değil **alınan üs sayısına** göre ölçülür (3 × Mk 77 ile de üs alınır).
Sayı sonuç metnindeki "Yok edilen üsler" satırlarından gelir. Sonuç metni olmayan maçlarda (≈) o uçakla verilen üs
hasarı, aynı uçağın sonuç metinli maçlarındaki üs başına hasarla sayıya çevrilir; sonuç metni hiç olmayan uçaklar
tahmin edilmez. Beceri sayfası üs aldığın ve almadığın maçların RP/SL'sini karşılaştırır; düşük K/D'yi üs bombalamayla
birlikte değerlendirir. Diğer oyuncuların üs sayısı replay'de kayıtlı olmadığı için lobi kıyası yapılmaz.

Filtreler (`stats` ve `battles`): `--vehicle fa_18c_late`, `--map İspanya`, `--last 20`,
`--since 2026-11-01`, `--type air|ground|all` (varsayılan: air).

Daha önce bir dosyaya yapıştırdığın sonuç metinleri için: `python -m blackbox add-results Mac_Sonuclari.txt`

Haritalar sonuç metinlerinden Türkçe isim öğrenir; elle isim vermek için:
`python -m blackbox maps` ve `python -m blackbox name-map air_vietnam "Vietnam"`

## Bilinen sınırlamalar
- RWR ve radar kilidi verisi hiçbir kaynakta (henüz) yok.
- Kazanma durumu yalnızca sonuç metninden gelir; replay, oyundan çıktığın anda kesilir.
- Replay formatı resmi değildir; topluluk araştırmasına dayanır (WTACRP, wrpl-inspector). Oyun güncellemesinden sonra bozulabilir.
- "En yakın düşman" yalnızca minimapte görünen (tespit edilmiş) düşmanları kapsar.

## Geliştirme
```powershell
python -m unittest discover tests
python dev/fake_wt_server.py --port 8112
python recorder/record.py --url http://127.0.0.1:8112
```
