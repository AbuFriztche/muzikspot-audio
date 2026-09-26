const form = document.getElementById("lookup-form");
const input = document.getElementById("spotify-url");
const button = document.getElementById("lookup-button");
const result = document.getElementById("result");
const status = document.getElementById("status");
let currentData = null;

function setText(id, value) {
  document.getElementById(id).textContent = value || "Bulunamadı";
}

function showStatus(message, error = false) {
  status.textContent = message;
  status.classList.remove("hidden");
  status.classList.toggle("error", error);
}

function duration(milliseconds) {
  if (!milliseconds) return null;
  const seconds = Math.round(milliseconds / 1000);
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}

function create(tag, className, content) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (content != null) node.textContent = content;
  return node;
}

function render(data) {
  currentData = data;
  refreshAudioButton();
  result.classList.remove("hidden");
  status.classList.add("hidden");
  const cover = document.getElementById("cover");
  cover.src = data.cover_url || "";
  cover.alt = `${data.title || "Albüm"} kapağı`;
  setText("kind", data.kind === "album" ? "ALBÜM" : "ŞARKI");
  setText("title", data.title);
  setText("artist-main", data.artist || "Sanatçı doğrulanamadı");
  setText("artist", data.artist);
  setText("producer", data.producer?.join(", "));
  setText("label", data.label);
  setText("date", data.date);
  setText("album", data.kind === "album" ? data.title : data.album);
  setText("genre", data.genre?.join(", "));
  setText("identifier", data.kind === "album" ? data.barcode : data.isrc?.join(", "));
  setText("duration", duration(data.duration_ms));

  const sources = document.getElementById("sources");
  sources.replaceChildren(...(data.sources || []).map(source => create("span", "source-pill", source)));

  const trackSection = document.getElementById("track-section");
  const tracks = document.getElementById("tracks");
  tracks.replaceChildren();
  if (data.tracks?.length) {
    trackSection.classList.remove("hidden");
    setText("track-count", `${data.tracks.length} parça`);
    for (const track of data.tracks) {
      const row = create("div", "track-row");
      const number = create("span", "track-number", `${track.disc || 1}.${track.number || "?"}`);
      const body = create("div", "track-body");
      body.append(create("strong", "", track.title || "Adsız parça"), create("small", "", track.artist || "Sanatçı bulunamadı"));
      const extra = create("div", "track-extra");
      if (track.producer?.length) extra.append(create("small", "producer-credit", `Yapımcı: ${track.producer.join(", ")}`));
      if (track.isrc?.length) extra.append(create("small", "track-isrc", `ISRC: ${track.isrc.join(", ")}`));
      extra.append(create("span", "", duration(track.duration_ms) || "—"));
      row.append(number, body, extra);
      tracks.append(row);
    }
  } else {
    trackSection.classList.add("hidden");
  }

  const note = document.getElementById("note");
  note.textContent = data.note || "";
  note.classList.toggle("hidden", !data.note);

  const player = document.getElementById("spotify-player");
  player.replaceChildren();
  const iframe = create("iframe", "");
  iframe.src = `https://open.spotify.com/embed/${data.kind}/${data.spotify_id}`;
  iframe.title = "Spotify oynatıcı";
  iframe.loading = "lazy";
  iframe.setAttribute("allow", "autoplay; clipboard-write; encrypted-media; fullscreen; picture-in-picture");
  player.append(iframe);

  result.scrollIntoView({behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth", block: "start"});
}

form.addEventListener("submit", async event => {
  event.preventDefault();
  if (button.disabled) return;
  button.disabled = true;
  result.classList.add("hidden");
  showStatus("Spotify ve MusicBrainz kayıtları aranıyor...");
  try {
    const response = await fetch("/api/lookup", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({url: input.value.trim()}),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Bilgiler alınamadı.");
    render(data);
  } catch (error) {
    showStatus(error.message || "Bilgiler alınamadı.", true);
  } finally {
    button.disabled = false;
  }
});

const audioStart = document.getElementById("start-audio");
const audioAvailability = document.getElementById("audio-availability");
const audioJobs = document.getElementById("audio-jobs");
let audioAvailable = false;
let availabilityAttempts = 0;

function refreshAudioButton() {
  audioStart.disabled = !audioAvailable || !currentData;
  audioStart.textContent = currentData?.kind === "album" ? "Albümü indir ↓" : "Şarkıyı MP3 indir ↓";
}

async function checkAudioAvailability() {
  availabilityAttempts += 1;
  let retry = false;
  try {
    const response = await fetch("/api/health");
    const data = await response.json();
    audioAvailable = response.ok && data.audio_available === true;
    retry = !audioAvailable && data.audio_state === "offline";
    document.getElementById("connection-state").classList.toggle("ready", audioAvailable);
    setText("connection-label", audioAvailable ? "İndirme hazır" : "Bilgi modu");
    audioAvailability.textContent = audioAvailable
      ? "İndirme hazır. Şarkı veya albümü MP3 olarak hazırlayabilirsin."
      : data.message || "İndirme hizmeti şu anda kullanılamıyor. Şarkı bilgilerini inceleyebilirsin.";
  } catch {
    audioAvailable = false;
    retry = true;
    document.getElementById("connection-state").classList.remove("ready");
    setText("connection-label", "Bilgi modu");
    audioAvailability.textContent = "İndirme hizmetine bağlanılamadı. Biraz sonra yeniden dene.";
  }
  if (retry && availabilityAttempts < 8) {
    setText("connection-label", "Bağlanıyor");
    audioAvailability.textContent = "İndirme hizmetine bağlanılıyor. Açılması yaklaşık bir dakika sürebilir...";
    setTimeout(checkAudioAvailability, 10000);
  }
  refreshAudioButton();
  if (audioAvailable) restoreAudioJobs();
}

function makeAudioJobCard(data, title) {
  const existing = [...audioJobs.children].find(card => card.dataset.jobId === data.id);
  if (existing) return existing;
  const card = create("div", "audio-job");
  card.dataset.jobId = data.id;
  card.append(create("strong", "", title || data.title || "Şarkı"),
    create("p", "audio-job-summary", "Başlıyor..."), create("div", "audio-job-files"));
  audioJobs.prepend(card);
  return card;
}

async function restoreAudioJobs() {
  try {
    const response = await fetch("/api/audio-jobs");
    if (!response.ok) return;
    const data = await response.json();
    for (const job of [...(data.jobs || [])].reverse()) {
      const card = makeAudioJobCard(job);
      if (["queued", "running", "done"].includes(job.state)) card.dataset.autoDownload = "true";
      renderAudioJob(job, card);
      if (["queued", "running", "done"].includes(job.state)) pollAudioJob(job.id, card);
    }
  } catch {
    // A temporary connection failure should not prevent a new download.
  }
}

function renderAudioJob(data, card) {
  const summary = card.querySelector(".audio-job-summary");
  const fileList = card.querySelector(".audio-job-files");
  summary.textContent = data.message || "İşleniyor...";
  summary.classList.toggle("error", data.state === "failed");
  if (data.error) summary.textContent += " " + data.error;
  fileList.replaceChildren();
  if (data.state !== "done" || !data.download) return;
  const link = create("a", "audio-file", `İndirme başlamadıysa buraya bas: ${data.download.name} ↓`);
  link.href = data.download.url;
  link.download = data.download.name;
  link.addEventListener("click", () => {
    if (card.dataset.awaitingDownload !== "true") {
      card.dataset.awaitingDownload = "true";
      pollAudioJob(data.id, card);
    }
  });
  fileList.append(link);
  if (card.dataset.autoDownload === "true") {
    card.dataset.autoDownload = "sent";
    card.dataset.awaitingDownload = "true";
    link.click();
  }
}

async function pollAudioJob(id, card) {
  try {
    const response = await fetch(`/api/audio-jobs/${id}`);
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "İndirme durumu alınamadı.");
    renderAudioJob(data, card);
    if (data.state === "queued" || data.state === "running" ||
        (data.state === "done" && card.dataset.awaitingDownload === "true")) {
      setTimeout(() => pollAudioJob(id, card), 2000);
    }
  } catch (error) {
    card.querySelector(".audio-job-summary").textContent = error.message;
  }
}

audioStart.addEventListener("click", async () => {
  if (!currentData || audioStart.disabled) return;
  audioStart.disabled = true;
  audioAvailability.textContent = "İndirme işi başlatılıyor...";
  try {
    const response = await fetch("/api/audio-jobs", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({url: currentData.spotify_url}),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "İndirme başlatılamadı.");
    const card = makeAudioJobCard(data, currentData.title);
    card.dataset.autoDownload = "true";
    renderAudioJob(data, card);
    pollAudioJob(data.id, card);
    audioAvailability.textContent = "İndirme başlatıldı. Başka bir şarkı veya albüm de başlatabilirsin.";
  } catch (error) {
    audioAvailability.textContent = error.message || "İndirme başlatılamadı.";
  } finally {
    refreshAudioButton();
  }
});

checkAudioAvailability();
