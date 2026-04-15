#!/usr/bin/env node
'use strict';

/**
 * Debug helper: extract one restored media message payload from Core/Message shard,
 * convert the stored JSON-string-with-control-bytes into a Buffer, and run native parseBinNet.
 *
 * Usage:
 *   node tools/debug_parse_binnet.js /path/to/Core/Message/<conv>.db [msgType]
 */

const path = require('path');
const { execFileSync } = require('child_process');

const dbPath = process.argv[2];
const msgType = Number(process.argv[3] || 2);

if (!dbPath) {
  console.error('Usage: node tools/debug_parse_binnet.js <message_shard.db> [msgType]');
  process.exit(2);
}

const addon = require(path.resolve(__dirname, '../native/nativelibs/db-cross-v4/prebuilt/linux/electron/x64/db-cross-v4-native.node'));

function getOneRowViaSqlite3Cli(p, mt) {
  // Use sqlite3 CLI to avoid needing npm deps in this repo.
  // Output as TSV with \t separators, no headers.
  const sql = [
    '.mode tabs',
    '.headers off',
    `SELECT cliMsgId, msgType, message FROM message WHERE msgType=${Number(mt)} AND message IS NOT NULL ORDER BY CAST(sendDttm AS INTEGER) DESC LIMIT 1;`,
  ].join('\n');

  const uri = `file:${p}?mode=ro&immutable=1`;
  const out = execFileSync('sqlite3', [uri], { input: sql, encoding: 'utf8' }).trimEnd();
  if (!out) return null;
  const parts = out.split('\t');
  return { cliMsgId: parts[0], msgType: Number(parts[1]), message: parts.slice(2).join('\t') };
}

async function main() {
  const row = getOneRowViaSqlite3Cli(dbPath, msgType);
  if (!row) {
    console.error('No matching row found.');
    process.exit(1);
  }

  // In these corrupted cases, `message` is stored as a JSON string literal (including quotes).
  // Example: "\"\\u0019\\u0012@...\""
  let decoded;
  try {
    decoded = JSON.parse(row.message);
  } catch {
    decoded = row.message;
  }

  // Many corrupted backups store *double-escaped* strings like "\\u0019\\u0012@..."
  // Convert those escape sequences into actual bytes before feeding to native TLV parser.
  if (typeof decoded === 'string' && decoded.includes('\\u')) {
    decoded = decoded.replace(/\\u([0-9a-fA-F]{4})/g, (_, h) => String.fromCharCode(parseInt(h, 16)));
    decoded = decoded.replace(/\\n/g, '\n').replace(/\\r/g, '\r').replace(/\\t/g, '\t').replace(/\\\\/g, '\\');
  }

  // Strip redundant surrounding quotes introduced by double-encoding.
  while (typeof decoded === 'string' && decoded.length >= 2 && decoded.startsWith('"') && decoded.endsWith('"')) {
    decoded = decoded.slice(1, -1);
  }

  const buf = Buffer.from(decoded, 'binary');
  const parsed = addon.parseBinNet(buf);

  function looksAscii(b) {
    let good = 0;
    for (const ch of b) {
      if (ch === 0) return false;
      if (ch === 9 || ch === 10 || ch === 13) { good++; continue; }
      if (ch >= 0x20 && ch <= 0x7e) { good++; continue; }
      return false;
    }
    return good > 0;
  }

  // Heuristic: some corrupted payloads look like 1-byte TLV (tag, len, value...).
  const tlv8 = [];
  for (let i = 0; i + 2 <= buf.length; ) {
    const tag = buf[i];
    const len = buf[i + 1];
    const next = i + 2 + len;
    if (next > buf.length) break;
    const val = buf.subarray(i + 2, next);
    if (looksAscii(val)) {
      tlv8.push({ tag, len, text: val.toString('utf8') });
    }
    i = next;
  }

  console.log(JSON.stringify({
    input: {
      dbPath,
      cliMsgId: row.cliMsgId,
      msgType: row.msgType,
      messageLen: row.message ? row.message.length : 0,
      decodedLen: decoded.length,
      bufLen: buf.length,
      bufHexPrefix: buf.subarray(0, 32).toString('hex'),
    },
    parsed,
    tlv8_ascii: tlv8.slice(0, 50),
  }, null, 2));
}

main().catch((e) => {
  console.error(String(e && e.stack || e));
  process.exit(1);
});

