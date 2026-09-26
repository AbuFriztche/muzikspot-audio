/* Small ZIP-store writer: every MP3 stays a separate file inside the archive. */
(function (root) {
  "use strict";
  const encoder = new TextEncoder();
  const table = new Uint32Array(256);
  for (let n = 0; n < 256; n++) {
    let value = n;
    for (let bit = 0; bit < 8; bit++) value = value & 1 ? 0xedb88320 ^ (value >>> 1) : value >>> 1;
    table[n] = value >>> 0;
  }

  function crc32(bytes) {
    let value = 0xffffffff;
    for (const byte of bytes) value = table[(value ^ byte) & 255] ^ (value >>> 8);
    return (value ^ 0xffffffff) >>> 0;
  }

  function dosTime(date) {
    return (date.getHours() << 11) | (date.getMinutes() << 5) | (date.getSeconds() >>> 1);
  }

  function dosDate(date) {
    return ((Math.max(1980, date.getFullYear()) - 1980) << 9) | ((date.getMonth() + 1) << 5) | date.getDate();
  }

  function zip(entries) {
    if (!entries.length || entries.length > 65535) throw new Error("Geçersiz dosya sayısı.");
    const parts = [];
    const central = [];
    const now = new Date();
    let offset = 0;
    let centralSize = 0;
    for (const entry of entries) {
      const name = encoder.encode(entry.name);
      const file = entry.bytes;
      if (name.length > 65535 || file.length > 0xffffffff || offset > 0xffffffff) throw new Error("ZIP için dosya çok büyük.");
      const crc = crc32(file);
      const local = new Uint8Array(30);
      const l = new DataView(local.buffer);
      l.setUint32(0, 0x04034b50, true);
      l.setUint16(4, 20, true);
      l.setUint16(6, 0x0800, true);
      l.setUint16(10, dosTime(now), true);
      l.setUint16(12, dosDate(now), true);
      l.setUint32(14, crc, true);
      l.setUint32(18, file.length, true);
      l.setUint32(22, file.length, true);
      l.setUint16(26, name.length, true);
      parts.push(local, name, file);

      const record = new Uint8Array(46);
      const c = new DataView(record.buffer);
      c.setUint32(0, 0x02014b50, true);
      c.setUint16(4, 20, true);
      c.setUint16(6, 20, true);
      c.setUint16(8, 0x0800, true);
      c.setUint16(12, dosTime(now), true);
      c.setUint16(14, dosDate(now), true);
      c.setUint32(16, crc, true);
      c.setUint32(20, file.length, true);
      c.setUint32(24, file.length, true);
      c.setUint16(28, name.length, true);
      c.setUint32(42, offset, true);
      central.push(record, name);
      centralSize += record.length + name.length;
      offset += local.length + name.length + file.length;
    }
    if (offset + centralSize > 0xffffffff) throw new Error("ZIP için toplam boyut çok büyük.");
    const end = new Uint8Array(22);
    const e = new DataView(end.buffer);
    e.setUint32(0, 0x06054b50, true);
    e.setUint16(8, entries.length, true);
    e.setUint16(10, entries.length, true);
    e.setUint32(12, centralSize, true);
    e.setUint32(16, offset, true);
    return new Blob([...parts, ...central, end], {type: "application/zip"});
  }

  const api = {zip};
  root.Mp3Zip = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof window !== "undefined" ? window : globalThis);
