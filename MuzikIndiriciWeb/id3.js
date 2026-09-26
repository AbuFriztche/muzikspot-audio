/* ID3v2.3 writer for user-supplied MP3 files. Audio frames are copied unchanged. */
(function (root) {
  "use strict";

  const encoder = new TextEncoder();

  function bytes(...parts) {
    const size = parts.reduce((total, part) => total + part.length, 0);
    const output = new Uint8Array(size);
    let offset = 0;
    for (const part of parts) {
      output.set(part, offset);
      offset += part.length;
    }
    return output;
  }

  function ascii(value) {
    return Uint8Array.from(value, char => char.charCodeAt(0));
  }

  function utf16(value) {
    const output = new Uint8Array(2 + value.length * 2);
    output.set([0xff, 0xfe]);
    for (let i = 0; i < value.length; i++) {
      const unit = value.charCodeAt(i);
      output[2 + i * 2] = unit & 255;
      output[3 + i * 2] = unit >>> 8;
    }
    return output;
  }

  function bigEndian(value) {
    return Uint8Array.of(value >>> 24, value >>> 16 & 255, value >>> 8 & 255, value & 255);
  }

  function synchsafe(value) {
    if (value >= 0x10000000) throw new Error("MP3 etiketi çok büyük.");
    return Uint8Array.of(value >>> 21 & 127, value >>> 14 & 127, value >>> 7 & 127, value & 127);
  }

  function frame(id, payload) {
    return bytes(ascii(id), bigEndian(payload.length), Uint8Array.of(0, 0), payload);
  }

  function textFrame(id, value) {
    if (value == null || value === "") return null;
    return frame(id, bytes(Uint8Array.of(1), utf16(String(value))));
  }

  function customFrame(description, value) {
    if (value == null || value === "") return null;
    return frame("TXXX", bytes(Uint8Array.of(1), utf16(description), Uint8Array.of(0, 0), utf16(String(value))));
  }

  function pictureFrame(image, mime) {
    if (!image || !image.length) return null;
    if (mime !== "image/jpeg" && mime !== "image/png") throw new Error("Kapak JPEG veya PNG olmalı.");
    return frame("APIC", bytes(Uint8Array.of(0), ascii(mime), Uint8Array.of(0, 3, 0), image));
  }

  function originalTagEnd(audio) {
    if (audio.length < 10 || String.fromCharCode(...audio.subarray(0, 3)) !== "ID3") return 0;
    const size = ((audio[6] & 127) << 21) | ((audio[7] & 127) << 14) | ((audio[8] & 127) << 7) | (audio[9] & 127);
    const footer = audio[3] === 4 && (audio[5] & 0x10) ? 10 : 0;
    const end = 10 + size + footer;
    if (end > audio.length) throw new Error("MP3 dosyasındaki mevcut etiket bozuk.");
    return end;
  }

  function isMpegHeader(audio, offset) {
    if (offset + 3 >= audio.length || audio[offset] !== 0xff || (audio[offset + 1] & 0xe0) !== 0xe0) return false;
    const version = (audio[offset + 1] >>> 3) & 3;
    const layer = (audio[offset + 1] >>> 1) & 3;
    const bitrate = (audio[offset + 2] >>> 4) & 15;
    const sampleRate = (audio[offset + 2] >>> 2) & 3;
    return version !== 1 && layer !== 0 && bitrate !== 0 && bitrate !== 15 && sampleRate !== 3;
  }

  function createTag(data, track, image, mime) {
    const frames = [];
    const add = item => { if (item) frames.push(item); };
    const title = track ? track.title : data.title;
    const artist = track ? (track.artist || data.artist) : data.artist;
    const album = data.kind === "album" ? data.title : data.album;
    const isrc = track ? track.isrc : data.isrc;
    const producer = track ? track.producer : data.producer;
    const duration = track ? track.duration_ms : data.duration_ms;
    add(textFrame("TIT2", title));
    add(textFrame("TPE1", artist));
    add(textFrame("TALB", album));
    add(textFrame("TPE2", data.kind === "album" ? data.artist : null));
    add(textFrame("TYER", data.date ? data.date.slice(0, 4) : null));
    add(textFrame("TCON", data.genre?.join(", ")));
    add(textFrame("TPUB", data.label));
    add(textFrame("TRCK", track?.number ? (data.tracks?.length ? `${track.number}/${data.tracks.length}` : track.number) : null));
    add(textFrame("TPOS", track?.disc));
    add(textFrame("TSRC", isrc?.[0]));
    add(textFrame("TLEN", duration));
    add(customFrame("PRODUCER", producer?.join(", ")));
    add(customFrame("BARCODE", data.barcode));
    add(customFrame("RELEASE_DATE", data.date));
    add(customFrame("SPOTIFY_URL", data.spotify_url));
    add(customFrame("MUSICBRAINZ_URL", data.musicbrainz_url));
    add(customFrame("LOOKUP_JSON", JSON.stringify({album: data, selected_track: track || null})));
    add(pictureFrame(image, mime));
    const body = bytes(...frames);
    return bytes(ascii("ID3"), Uint8Array.of(3, 0, 0), synchsafe(body.length), body);
  }

  function tagMp3(buffer, data, track, image, mime) {
    const audio = buffer instanceof Uint8Array ? buffer : new Uint8Array(buffer);
    const offset = originalTagEnd(audio);
    let frameFound = false;
    for (let i = offset; i < Math.min(audio.length - 3, offset + 4096); i++) {
      if (isMpegHeader(audio, i)) { frameFound = true; break; }
    }
    if (!frameFound) throw new Error("Seçilen dosya geçerli bir MP3 gibi görünmüyor.");
    return bytes(createTag(data, track, image, mime), audio.subarray(offset));
  }

  const api = {tagMp3};
  root.Mp3Tagger = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof window !== "undefined" ? window : globalThis);
