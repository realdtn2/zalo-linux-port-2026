#!/usr/bin/env python3
"""
Build the user's ORIGINAL linux addon implementation into a standalone .node file
without overwriting the currently-installed addon.

Output:
  reverse-engineering/old-linux/db-cross-v4-native.old.node
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

BUILD_DIR = Path("/tmp/db-cross-build-old")
BUILD_DIR.mkdir(parents=True, exist_ok=True)

pkg = {
    "name": "db-cross-v4-linux-old",
    "version": "1.0.0",
    "description": "Original Linux reimplementation (old variant) for comparison",
    "main": "index.js",
    "scripts": {"build": "node-gyp configure build"},
    "dependencies": {"node-addon-api": "^5.0.0", "node-gyp": "^10.0.0"},
}
(BUILD_DIR / "package.json").write_text(json.dumps(pkg, indent=2))

gyp = """{
  "targets": [{
    "target_name": "db-cross-v4-native",
    "sources": ["src/main.cc"],
    "include_dirs": ["<(module_root_dir)/node_modules/node-addon-api"],
    "dependencies": ["<!(node -p \\"require('node-addon-api').gyp\\")"],
    "cflags!": ["-fno-exceptions"],
    "cflags_cc!": ["-fno-exceptions"],
    "defines": ["NAPI_DISABLE_CPP_EXCEPTIONS"],
    "libraries": ["-llzma", "-lcrypto"],
    "cflags_cc": ["-std=c++17", "-O2"]
  }]
}"""
(BUILD_DIR / "binding.gyp").write_text(gyp)

(BUILD_DIR / "src").mkdir(parents=True, exist_ok=True)

src = r'''
#include <napi.h>
#include <openssl/evp.h>
#include <openssl/aes.h>
#include <lzma.h>
#include <fstream>
#include <vector>
#include <string>
#include <filesystem>
#include <iostream>
#include <algorithm>

namespace fs = std::filesystem;

struct FileEntry { std::string name; uint32_t size; };

static uint32_t read_u32_be(const uint8_t* p) {
    return (p[0] << 24) | (p[1] << 16) | (p[2] << 8) | p[3];
}

static std::vector<uint8_t> read_file(const std::string& path) {
    std::ifstream f(path, std::ios::binary | std::ios::ate);
    if (!f) throw std::runtime_error("Cannot open input: " + path);
    size_t size = f.tellg();
    f.seekg(0, std::ios::beg);
    std::vector<uint8_t> buf(size);
    if (f.read((char*)buf.data(), size)) return buf;
    throw std::runtime_error("Failed to read: " + path);
}

struct DecryptResult { int code; std::string err; };

static DecryptResult process_zdb4_v2(
    const std::string& input_path,
    const std::string& output_path,
    const std::string& private_key_str,
    std::function<void()> progress_cb) {

    try {
        auto ct = read_file(input_path);

        std::vector<uint8_t> aes_key(32, 0);
        for(size_t i = 0; i < 32 && i < private_key_str.length(); ++i) {
            aes_key[i] = private_key_str[i];
        }

        uint8_t iv[16] = {0};

        EVP_CIPHER_CTX* ctx = EVP_CIPHER_CTX_new();
        EVP_DecryptInit_ex(ctx, EVP_aes_256_cbc(), nullptr, aes_key.data(), iv);
        EVP_CIPHER_CTX_set_padding(ctx, 0);

        std::vector<uint8_t> pt(ct.size() + AES_BLOCK_SIZE);
        int len1 = 0, len2 = 0;
        EVP_DecryptUpdate(ctx, pt.data(), &len1, ct.data(), ct.size());
        EVP_DecryptFinal_ex(ctx, pt.data() + len1, &len2);
        EVP_CIPHER_CTX_free(ctx);
        pt.resize(len1 + len2);

        if (pt.size() < 16 || memcmp(pt.data(), "ZDB4.0", 6) != 0) {
            return {-1, "Invalid ZDB4.0 Magic Header"};
        }

        size_t off = 14;
        uint32_t file_count = read_u32_be(pt.data() + off); off += 4;

        std::vector<FileEntry> files;
        for(uint32_t i = 0; i < file_count; i++) {
            if (off + 4 > pt.size()) return {-2, "Truncated file table"};
            uint32_t nlen = read_u32_be(pt.data() + off); off += 4;

            if (off + nlen + 4 > pt.size()) return {-2, "Truncated file table names"};
            std::string name((char*)pt.data() + off, nlen); off += nlen;

            uint32_t size = read_u32_be(pt.data() + off); off += 4;
            files.push_back({name, size});
        }

        lzma_stream strm = LZMA_STREAM_INIT;
        lzma_ret ret = lzma_stream_decoder(&strm, UINT64_MAX, LZMA_CONCATENATED);
        if (ret != LZMA_OK) return {-3, "Failed to init liblzma decoder"};

        strm.next_in = pt.data() + off;
        strm.avail_in = pt.size() - off;

        fs::create_directories(output_path);

        std::vector<uint8_t> out_buf(65536);
        size_t file_idx = 0;
        size_t bytes_written_for_current_file = 0;
        std::ofstream current_out;

        if (!files.empty()) {
            current_out.open(output_path + "/" + files[file_idx].name, std::ios::binary);
        }

        do {
            strm.next_out = out_buf.data();
            strm.avail_out = out_buf.size();

            ret = lzma_code(&strm, LZMA_RUN);

            size_t decompressed_bytes = out_buf.size() - strm.avail_out;
            size_t buf_off = 0;

            while (buf_off < decompressed_bytes && file_idx < files.size()) {
                size_t needed = files[file_idx].size - bytes_written_for_current_file;
                size_t available = decompressed_bytes - buf_off;
                size_t to_write = std::min(needed, available);

                if (current_out.is_open()) {
                    current_out.write((char*)out_buf.data() + buf_off, to_write);
                }

                bytes_written_for_current_file += to_write;
                buf_off += to_write;

                if (bytes_written_for_current_file == files[file_idx].size) {
                    if (current_out.is_open()) current_out.close();

                    // callback per file
                    if (progress_cb) progress_cb();

                    file_idx++;
                    bytes_written_for_current_file = 0;

                    if (file_idx < files.size()) {
                        current_out.open(output_path + "/" + files[file_idx].name, std::ios::binary);
                    }
                }
            }
        } while (ret == LZMA_OK);

        lzma_end(&strm);
        if (current_out.is_open()) current_out.close();

        return {0, ""};
    } catch (const std::exception& e) {
        return {-99, e.what()};
    }
}

Napi::Value DecompressAndDecryptDb_V2(const Napi::CallbackInfo& info) {
    Napi::Env env = info.Env();
    auto ret = Napi::Object::New(env);

    if (info.Length() < 3 || !info[0].IsString() || !info[1].IsString() || !info[2].IsString()) {
        ret.Set("result", -1);
        ret.Set("inner_error", Napi::String::New(env, "Invalid args"));
        ret.Set("error_message", Napi::String::New(env, "Invalid args"));
        return ret;
    }

    Napi::FunctionReference* cb_ref = nullptr;
    if (info.Length() >= 4 && info[3].IsFunction()) {
        cb_ref = new Napi::FunctionReference();
        *cb_ref = Napi::Persistent(info[3].As<Napi::Function>());
    }

    auto progress_cb = [&]() {
        if (cb_ref && !cb_ref->IsEmpty()) cb_ref->Call({});
    };

    auto r = process_zdb4_v2(
        info[0].As<Napi::String>().Utf8Value(),
        info[1].As<Napi::String>().Utf8Value(),
        info[2].As<Napi::String>().Utf8Value(),
        progress_cb
    );

    if (cb_ref) delete cb_ref;

    ret.Set("result", Napi::Number::New(env, r.code));
    ret.Set("inner_error", Napi::String::New(env, r.err));
    ret.Set("error_message", Napi::String::New(env, r.err));
    return ret;
}

Napi::Value DecompressAndDecryptDb(const Napi::CallbackInfo& info) {
    Napi::Env env = info.Env();
    auto ret = Napi::Object::New(env);
    ret.Set("result", -1);
    ret.Set("err_message", Napi::String::New(env, "V1 format not implemented"));
    return ret;
}

Napi::Value ParseBinNet(const Napi::CallbackInfo& info) {
    Napi::Env env = info.Env();
    auto ret = Napi::Object::New(env);
    ret.Set("result", Napi::Number::New(env, 0));
    ret.Set("data",   Napi::Object::New(env));
    ret.Set("error_message", Napi::String::New(env, ""));
    return ret;
}

Napi::Object Init(Napi::Env env, Napi::Object exports) {
    exports.Set("decompressAndDecryptDb", Napi::Function::New(env, DecompressAndDecryptDb));
    exports.Set("decompressAndDecryptDb_V2", Napi::Function::New(env, DecompressAndDecryptDb_V2));
    exports.Set("parseBinNet", Napi::Function::New(env, ParseBinNet));
    return exports;
}

NODE_API_MODULE(db_cross_v4_native, Init)
'''
(BUILD_DIR / "src" / "main.cc").write_text(src)

# build
build_sh = f"""#!/bin/bash
set -e
cd "{BUILD_DIR}"
npm install node-addon-api 2>&1 >/dev/null
npx node-gyp configure --target=22.3.27 --arch=x64 --dist-url=https://www.electronjs.org/headers build 2>&1 >/dev/null
"""
(BUILD_DIR / "build.sh").write_text(build_sh)
os.chmod(BUILD_DIR / "build.sh", 0o755)
subprocess.run([str(BUILD_DIR / "build.sh")], check=True)

src_node = BUILD_DIR / "build/Release/db-cross-v4-native.node"
if not src_node.exists():
    raise SystemExit(f"Missing build output: {src_node}")

out_dir = Path(__file__).resolve().parents[1] / "reverse-engineering" / "old-linux"
out_dir.mkdir(parents=True, exist_ok=True)
dst = out_dir / "db-cross-v4-native.old.node"
shutil.copy2(src_node, dst)
print(f"[OK] Built old addon: {dst}")

