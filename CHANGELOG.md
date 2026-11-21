# Değişiklik günlüğü

Bu projedeki önemli değişiklikler bu dosyada tutulur. Biçim [Keep a Changelog](https://keepachangelog.com/tr-TR/1.1.0/)
esaslıdır; sürüm numaraları [Anlamsal Sürümleme](https://semver.org/lang/tr/) kurallarını izler.
1.0'dan önceki sürümler geriye dönük olarak commit geçmişinden çıkarılmıştır.

## [0.10.1] - 2026-11-22

### Eklendi
- Genişletilmiş README: özellikler, ekran görüntüleri, kurulum, komut tablosu, mimari şeması, analiz yöntemleri.
- Bu değişiklik günlüğü.
- MIT lisansı.

## [0.10.0] - 2026-11-22

### Eklendi
- **Gelişim** paneli (Beceri): son 10 maçlık hareketli ortalamayla K/D, üs/maç, RP/dk ve IR füzesiyle ölüm payı;
  kara için K/D, kill/maç, bölge/maç, skor.
- Üs koşusu zamanlaması: ilk üssün ortanca zamanı, aynı maçta üsler arası süre, üs almadan düşme oranı,
  üs aldığın silahlar; çoğu ölüm üsten önce geliyorsa yeni bir zayıf yön.
- Araç karşılaştırması: ortalama ilk ölüm dakikası ve düşmeden biten maç oranı.
- Kara: replay sonuçlarından bölge ele geçirme ve lobiyle kıyası; kendi araçlarına göre kill/ölüm tablosu;
  Haritalar ve Araçlar sayfalarında bölge/maç sütunu.
- Oyuncu profilleri: `setup <ad> --add`, her oyuncu için ayrı veritabanı, arayüzde oyuncu seçici,
  komut satırında `--player`. Sonuç metinleri yalnızca replay'i eşleşen profile sayılır.

### Değişti
- Multipath eşiği radar irtifası **100 m → 60 m** (oyunun güncel davranışı); telemetri yeniden analiz edildi.

## [0.9.0] - 2026-11-22

### Eklendi
- `BlackBox.bat` ve `python -m blackbox start`: kaydedici, pano izleyici, web arayüzü ve **otomatik içe aktarma**
  tek pencerede. Yeni replay, kayıt ya da sonuç metni gelince açık sayfa kendini yeniler.
- Dakika başına RP/SL: Özet, Araçlar, Haritalar ve üs karşılaştırmasında.
- Haritalar: üs/maç, ilk üs ve ilk ölüm dakikası; üs bombalamaya en uygun ve en zor haritalar.
- Grind: sonuç metni eksik maçların listesi.

## [0.8.0] - 2026-11-21

### Eklendi
- Üs bombalama, ton hasarına göre değil **alınan üs sayısına** göre: sonuç metnindeki "Yok edilen üsler".
  Sonuç metni olmayan maçlarda uçak bazında kalibre edilmiş tahmin (≈).
- Beceri'de üs bombalama paneli: üs/maç, üs alınan maç oranı, etki (hava kill + üs), üs alınan ve alınmayan maçların RP/SL'si.
- Özet KPI'ı, Maçlar listesinde ve maç detayında üs sayısı.

### Değişti
- Üs bombalıyorsan düşük K/D zayıf yön değil, not olarak gösterilir.

### Düzeltildi
- Sürekli Çarpışmalar (Enduring Confrontation) sonuç metinleri replay'lerine bağlanıyor ve hava maçı sayılıyor.

## [0.7.0] - 2026-11-21

### Eklendi
- Kara muharebeleri: replay'deki savaş türünden mod tespiti; kara maçlarında kill = kara + hava kill.
- Kara Beceri sayfası: seni vuran araç türü (tank, SPAA, uçak, helikopter) ve mühimmat türü, lobiyle kıyas.
- Tüm lobilerden öğrenilen araç türü tablosu; yeniden doğan araçların kurbanları saldıran taraftaki kimliklerle eşleniyor.
- Özet sayfasında güçlü ve zayıf yönler paneli.

## [0.6.0] - 2026-11-21

### Eklendi
- Beceri analizi: silah sınıfları (radar/IR füze, top, SAM), aynı maçlardaki lobiye göre ölüm nedenleri.
- Vurulmadan önceki 15 saniye: en yakın düşmana göre yön (sıcak / notch / soğuk), multipath, G, dönüş, hız ve irtifa.
- Enerji, art yakıcı ve takımın önünde uçma payı; somut önerilerle bulgular.

### Düzeltildi
- Veritabanı şema yükseltmesi açık dosyayı silmek yerine tabloları yerinde yeniden kurar.
- Batı uçaklarında radar irtifası feet cinsinden geliyordu; metreye çevriliyor.
- Orta genişlikte sekme çubuğunun daralması, KPI'larda yüzde işaretinin sırası.

## [0.5.0] - 2026-11-21

### Eklendi
- Yerel web arayüzü (`python -m blackbox web`): Özet, Maçlar, maç detayı (zaman çizelgesi, uçuş profili, rota,
  ödüller, takımlar), Silahlar, Haritalar, Araçlar, Grind. Dört renk teması, filtreler, arayüzden içe aktarma.

## [0.4.0] - 2026-11-21

### Eklendi
- Pano izleyici: hangarda kopyalanan savaş sonuçları `results/` klasörüne kaydedilir.
- Savaş sonucu metni ayrıştırıcı: zafer/yenilgi, SL/RP, tamir, aktivite, ödül kalemleri.
- Üç kaynağı (telemetri, replay, sonuç metni) oturum kimliğiyle birleştiren maç tablosu.
- `stats`: lobi kıyası, grind, araç/harita kırılımı, silahlar, ölüm zamanlaması; `--type air|ground|all`.
- Yeni komutlar: `battles`, `battle`, `add-results`, `maps`, `name-map`.

### Düzeltildi
- Maksimum G, isabet ve çarpma anlarındaki ani sıçramaları yok sayar.

## [0.3.0] - 2026-11-21

### Eklendi
- Replay (`.wrpl`) okuyucu: başlık (harita, mod, oturum), zstd paket akışı, kill kayıtları (kim, kimi, hangi silahla)
  ve sonuç bloğu (oyuncular, takımlar, kill, füzeden kaçış).

### Düzeltildi
- İçe aktarma, kaydedicinin hâlâ yazdığı oturumu almaz.

## [0.2.0] - 2026-11-21

### Eklendi
- Türkçe ve İngilizce kill feed ayrıştırıcı.
- Telemetriden yaşam tespiti, ölüm anı (irtifa, hız, G, en yakın düşman) ve uçuş istatistikleri.
- SQLite veritabanı ve ilk komut satırı (`setup`, `import`, `stats` ...).

## [0.1.0] - 2026-11-21

### Eklendi
- Oyunun yerel 8111 arayüzünü maç boyunca kaydeden telemetri kaydedici ve oturum inceleyici.
- Oyunsuz test için sahte 8111 sunucusu.

[0.10.1]: https://github.com/EnderkingTR/War-Thunder-Black-Box/compare/249b1bf...HEAD
[0.10.0]: https://github.com/EnderkingTR/War-Thunder-Black-Box/compare/440275e...249b1bf
[0.9.0]: https://github.com/EnderkingTR/War-Thunder-Black-Box/compare/b44fd23...440275e
[0.8.0]: https://github.com/EnderkingTR/War-Thunder-Black-Box/compare/0bcae68...b44fd23
[0.7.0]: https://github.com/EnderkingTR/War-Thunder-Black-Box/compare/0a3b3c8...0bcae68
[0.6.0]: https://github.com/EnderkingTR/War-Thunder-Black-Box/compare/39a39f5...0a3b3c8
[0.5.0]: https://github.com/EnderkingTR/War-Thunder-Black-Box/compare/e2284c9...39a39f5
[0.4.0]: https://github.com/EnderkingTR/War-Thunder-Black-Box/compare/62036b4...e2284c9
[0.3.0]: https://github.com/EnderkingTR/War-Thunder-Black-Box/compare/ed6e21b...62036b4
[0.2.0]: https://github.com/EnderkingTR/War-Thunder-Black-Box/compare/9aaff5b...ed6e21b
[0.1.0]: https://github.com/EnderkingTR/War-Thunder-Black-Box/commit/9aaff5b
