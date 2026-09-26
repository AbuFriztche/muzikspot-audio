import {copyFile, mkdir} from "node:fs/promises";
import {fileURLToPath} from "node:url";

const root = new URL("./", import.meta.url);
const output = new URL("public/", root);
await mkdir(output, {recursive: true});
// Publish only browser assets; never expose Python source, settings, or audio files.
for (const file of ["index.html", "style.css", "app.js", "particles.js"]) {
  await copyFile(new URL(file, root), new URL(file, output));
}
console.log(`Site hazır: ${fileURLToPath(output)}`);
