import sharp from "sharp";
import { readFileSync } from "fs";
import { dirname, join } from "path";
import { fileURLToPath } from "url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const svgPath = join(root, "public", "favicon.svg");
const iconsDir = join(root, "public", "icons");
const svg = readFileSync(svgPath);

async function writePng(size, filename) {
  await sharp(Buffer.from(svg)).resize(size, size).png().toFile(join(iconsDir, filename));
}

async function writeMaskable(size, filename) {
  const inner = Math.round(size * 0.72);
  const innerBuf = await sharp(Buffer.from(svg)).resize(inner, inner).png().toBuffer();
  await sharp({
    create: {
      width: size,
      height: size,
      channels: 4,
      background: { r: 3, g: 105, b: 161, alpha: 1 },
    },
  })
    .composite([{ input: innerBuf, gravity: "center" }])
    .png()
    .toFile(join(iconsDir, filename));
}

await writePng(192, "icon-192.png");
await writePng(512, "icon-512.png");
await writeMaskable(512, "icon-512-maskable.png");

console.log("Icons generated from public/favicon.svg");
