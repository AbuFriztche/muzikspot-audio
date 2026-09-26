# Müzik Bilgisi

Spotify şarkı veya albüm bağlantısını yapıştır. Site Spotify oEmbed ve aynı URL'ye bağlı MusicBrainz kaydından kapak, sanatçı, tarih, label, yapımcı ve parça listesini bulabildiği kadar gösterir. Eksik kredileri tahmin etmez.

Yerel sürümde **Şarkıyı / Albümü MP3 indir** düğmesi spotDL ile YouTube veya YouTube Music üzerinde eşleşen sesi bulur. Ses Spotify'dan alınmaz. Her parça ayrı MP3 olur; spotDL şarkı, albüm, sanatçı, tarih ve kapağı dosya içine ekler. MusicBrainz'de bulunan yapımcı ve label bilgisi de etiketlere eklenir. Eşleşen sesin doğru parça olduğunu dinleyerek kontrol edin. Hazırlama tamamlanınca tarayıcının normal indirmesi otomatik başlar. Tek parça MP3 olarak, birden fazla parça ise ayrı MP3 dosyalarını içeren ZIP olarak gönderilir. Dosyaların kaydedileceği yeri tarayıcının indirme ayarları belirler. Sunucudaki geçici kopya gönderimden sonra silinir; alınmayan dosyalar 15 dakika sonra temizlenir. En çok üç indirme işi aynı anda başlatılabilir; albüm parçalarını spotDL paralel işler.

Bulunan metadata'nın tamamı ayrıca MP3 içindeki `MUZIK_BILGISI_JSON` etiketine yazılır. Devam eden işler sayfa yenilendiğinde yeniden yüklenir. Yapımcı kredisi yalnızca ilgili parça için doğrulanabildiğinde standart etikete eklenir.

## Yerelde çalıştırma

Bu bilgisayarda Python ortamı ve spotDL kuruldu. **Baslat.bat** dosyasına veya masaüstündeki kısa yola çift tıklayın. Site http://127.0.0.1:8765/ adresinde açılır.

Başka bilgisayarda kurulum için Python 3.12+ ve FFmpeg gerekir:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-local.txt
.\Baslat.bat
```

FFmpeg sistem PATH içinde bulunmalıdır. spotDL ağdan eşleşen sesi bulamadığında veya kaynak erişimi kısıtlandığında iş hata durumuna geçer; başka kaynak eşleşmesini garanti etmez.

## Vercel'e aktarma

Vercel yapılandırması hazır: cam efektli arayüz, parçacık animasyonu, metadata sorgusu ve uzak indirme sunucusu bağlantısı. Hareket azaltma tercihi seçildiğinde animasyonlar durur.

Vercel projesinin kök dizinini `MuzikIndiriciWeb` seçin. `vercel.json` yalnızca tarayıcı dosyalarını `public/` içine hazırlatır; Python kaynakları ve geçici ses dosyaları statik siteye açılmaz. Bilgi sorgusu Vercel'deki `api/lookup.py` üzerinden çalışır.

MP3/ZIP için ayrı Python sunucusunu `Dockerfile` ile çalıştırın. Vercel'e `AUDIO_BACKEND_URL` ve `AUDIO_BACKEND_TOKEN` ortam değişkenlerini ekleyin. Vercel küçük JSON isteklerini iletir; dosya hazır olduğunda süreli bağlantıyla Python sunucusuna yönlendirir. Dosya normal tarayıcı indirmesiyle gelir. Anahtar tarayıcıya gönderilmez, işler tarayıcı oturumuna göre ayrılır.

Adım adım kurulum ve sınırlar: [DEPLOYMENT.md](DEPLOYMENT.md). Sunucu bağlanmadan bilgi sorgusu çalışır, indirme düğmesi devre dışı kalır.
