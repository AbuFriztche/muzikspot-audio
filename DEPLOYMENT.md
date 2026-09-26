# Vercel'e hazırlama ve indirme sunucusu

## Mimari

Tarayıcı → Vercel (arayüz, metadata, iş başlatma ve durum sorguları).
Vercel → ayrı Python sunucusu (spotDL + FFmpeg, arka plan işleri).
Hazır dosya → süreli imzalı yönlendirme → doğrudan Python sunucusundan tarayıcı indirmesi.

MP3/ZIP dosyası Vercel Function içinden taşınmaz. Ses Spotify'dan alınmaz; alternatif kaynakta bulunan eşleşme kullanılır. Erişim ve eşleşme garanti edilmez.

## 1. Python indirme sunucusu

Docker çalıştırabilen, sürekli açık bir sunucuda bu proje klasöründen:

```sh
docker build -t muzik-audio .
```

Güçlü bir anahtar oluşturun; çıktıyı Vercel ve Python sunucusunda aynı kullanın:

```sh
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Sunucunun ortam değişkenlerine `AUDIO_BACKEND_TOKEN` olarak bu anahtarı ekleyin. Docker'ı anahtarı ortamdan alarak çalıştırın:

```sh
docker run -d --restart unless-stopped --name muzik-audio -p 8080:8080 -e AUDIO_BACKEND_TOKEN muzik-audio
```

Barındırma paneli kullanıyorsanız Dockerfile'ı seçin, portu `8080`, sağlık kontrolünü `/readyz` ayarlayın. `AUDIO_BACKEND_TOKEN` zorunludur. HTTPS adresi sağlayın: örneğin `https://audio.senin-alan-adin.com`. TLS'yi barındırma hizmeti veya ters proxy sağlamalıdır.

Docker olmadan Python 3.13, FFmpeg ve `requirements-local.txt` kurulabilir. `HOST=0.0.0.0`, `PORT=8080`, `AUDIO_BACKEND_TOKEN` ortam değişkenleriyle `python app.py --no-browser` çalıştırılır. Anahtar olmadan dışa açık çalıştırma reddedilir. Yerelde `Baslat.bat` aynı şekilde anahtarsız çalışmaya devam eder.

### Render kurulumu

`render.yaml` Docker tabanlı, Frankfurt bölgesinde **Free** planlı tek bir Web Service tanımlar. Kaynak kodu özel bir GitHub deposuna yükleyin; Render'a yalnızca bu depoya erişim verin. Blueprint kurulumunda bu depoyu seçin ve `AUDIO_BACKEND_TOKEN` için yukarıdaki komutla oluşturulan anahtarı girin. Anahtarı depoya eklemeyin. Web Service formunu kullanırsanız Runtime Docker, Instance Type Free, Dockerfile `./Dockerfile`, Health Check Path `/readyz`, `HOST=0.0.0.0` ve `PORT=8080` ayarlarını seçin.

Free servis 15 dakika kullanılmadığında uyur; yeniden açılması yaklaşık bir dakika sürebilir. Vercel arayüzü bağlantı kurulamadığında durumu sınırlı sayıda otomatik yeniden kontrol eder. Free planın işlemci ve bellek sınırları yoğun indirmeyi karşılamayabilir; bu plan üzerinde gerçek dosya indirmesi ayrıca doğrulanmalıdır. Uyku veya yeniden başlatma sırasında geçici dosyalar ve bekleyen işler kaybolabilir.

[Render Docker](https://render.com/docs/docker), [Blueprint yapılandırması](https://render.com/docs/blueprint-spec), [Free plan sınırları](https://render.com/docs/free).

## 2. Vercel projesi

1. Projeyi içeri aktarın. **Root Directory:** `MuzikIndiriciWeb` (bu klasörü tek başına yüklediyseniz kök dizin).
2. **Framework Preset:** Other. Build Command `node build.mjs`, Output Directory `public`; dosyadaki `vercel.json` bunları zaten tanımlar.
3. **Settings → Environment Variables** altında şu iki değeri ekleyin:

| Değişken | Değer |
| --- | --- |
| `AUDIO_BACKEND_URL` | Python sunucusunun HTTPS adresi; sonunda `/api` olmadan |
| `AUDIO_BACKEND_TOKEN` | Python sunucusundakiyle aynı gizli anahtar |

4. Kullanacağınız Production / Preview ortamlarını seçin, ardından Deploy / Redeploy yapın. Preview arayüzünün de gerçek indirmeler başlatabileceğini göz önünde bulundurun.

CLI kullanıyorsanız bu proje klasöründe `vercel` ile önizleme, `vercel --prod` ile üretim yayını oluşturabilirsiniz. Bu hazırlık sırasında yayın yapılmaz.

`.env.example` bir şablondur; uygulama bunu otomatik okumaz. Anahtarı JavaScript'e, HTML'e veya depoya yazmayın. `.gitignore` ve `.vercelignore` gerçek `.env` dosyalarını hariç tutar.

## 3. Çalıştığını kontrol etme

- Vercel adresini açın: sağ üstte **İndirme hazır** görünmeli.
- Spotify şarkı/albüm linkini girin; kapak ve bulunan krediler görünmeli.
- **İndir** düğmesine basın. Tek parça MP3, çok parçalı albüm ayrı MP3'leri içeren ZIP gönderir.
- Sayfa yenilendiğinde aynı tarayıcının devam eden işleri geri gelir. Başka tarayıcı oturumu bu işleri listeleyemez.
- Sunucu bağlı değilse **Bilgi modu** görünür. Metadata kullanılabilir; indirme başlatılmaz.

## Çalışma sınırları

Bu sürüm tek, sürekli çalışan Python sunucusu içindir. İş kuyruğu bellektedir; yeniden başlatma işleri kaybettirir. Birden fazla replica / otomatik ölçekleme kullanılmamalı. Kalıcı kuyruk veya kullanıcı hesabı içermez; herkese açık yoğun kullanım için bunlar ayrıca eklenmelidir.

Aynı anda en çok üç iş çalışır. Dosyalar gönderim tamamlanınca veya hazırlandıktan 15 dakika sonra temizlenir. Tarayıcı indirme bağlantısı 5 dakika geçerlidir ve ilgili iş ile oturuma bağlıdır. Tarayıcı çerezleri silinirse eski oturuma ait işler geri getirilemez. Kaynağın ağ veya bölge kısıtlamaları indirmeyi engelleyebilir.

## Kaynaklar

- [Vercel Python /api Functions](https://vercel.com/docs/functions/runtimes/python/api-directory)
- [vercel.json yapılandırması](https://vercel.com/docs/project-configuration/vercel-json)
- [Vercel Functions sınırları](https://vercel.com/docs/functions/limitations)
