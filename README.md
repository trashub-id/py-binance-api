# Event-Driven Binance Futures Bot (USDT-M)

Bot trading otomatis untuk pasar **Binance Futures (USDT-M)** yang beroperasi dengan arsitektur _Event-Driven WebSocket_ (tanpa *REST polling*). App ini menerima sinyal melalui Webhook, meletakkan _Entry Order_ bervalidasi ekstra, dan otomatis menempatkan _Take Profit_ (TP) serta _Stop Loss_ (SL) **hanya setelah** order Entry berstatus `FILLED`.

Berisi sistem integrasi _Row-Level Security_ (RLS) milik **Supabase** untuk dokumentasi log presisi secara seketika (*real-time*).

## 🚀 Fitur Utama
1. **Webhook Interface (FastAPI)**: Siap dihubungkan dengan TradingView Alerts atau layanan manapun.
2. **True Event-Driven (WebSocket)**: Menunggu respon dari `USER_DATA_STREAM` alih-alih melakukan *polling* secara membabi buta.
3. **Konversi Harga & Kuantitas Pintar**: Menghitung secara dinamis parameter `tickSize` dan `stepSize` bursa.
4. **Keamanan Ekstra (Supabase RLS)**: Memaksa kebijakan tanpa akses bagi _user_ tanpa kunci khusus untuk meretas database.

---

## 📡 Dokumentasi Payload Webhook

Kirimkan JSON *Payload* ini melalui permintaan `HTTP POST` ke *endpoint* `/webhook` aplikasi Anda (contoh lokal: `http://127.0.0.1:8000/webhook`).

### 1. Sinyal Jaring Beli (LONG) - *Limit / Post-Only*
Digunakan jika mendapat sinyal untuk "Beli jika harga menyentuh angka tertentu".
Penggunaan `POST_ONLY` menjamin Anda bertindak sebagai *Maker* (biaya _fee_ jauh lebih hemat).

```json
{
  "symbol": "BTCUSDT",
  "side": "BUY",
  "quantity": 0.01,
  "entry": { "type": "POST_ONLY", "price": 60000 },
  "tp": { "type": "LIMIT", "price": 61000 },
  "sl": { "type": "STOP_MARKET", "price": 59500 } 
}
```

### 2. Sinyal Jaring Jual (SHORT) - *Limit / Post-Only*
Sama seperti sinyal pertama namun berlawanan spesifik (posisi *Sell*, TP berada di bawah, dan SL berada di atas).

```json
{
  "symbol": "ETHUSDT",
  "side": "SELL",
  "quantity": 0.2,
  "entry": { "type": "POST_ONLY", "price": 4000 },
  "tp": { "type": "LIMIT", "price": 3800 },
  "sl": { "type": "STOP_MARKET", "price": 4100 } 
}
```

### 3. Eksekusi FOMO (MARKET) - *Instan*
Sinyal untuk langsung memasuki pasar di saat harga terkini (*Taker*). Pada tipe `MARKET`, parameter _price_ untuk _Entry_ tidak akan dianggap/dipakai oleh Binance (Anda bisa mengisi sembarang angka atau `0`).

```json
{
  "symbol": "SOLUSDT",
  "side": "BUY",
  "quantity": 2.5,
  "entry": { "type": "MARKET", "price": 0 },
  "tp": { "type": "LIMIT", "price": 150 },
  "sl": { "type": "STOP_MARKET", "price": 135 } 
}
```

> **INFO:** Order TP (`LIMIT`) akan otomatis dijalankan dengan setelan **`reduceOnly=True`**. Sedangkan untuk SL (`STOP_MARKET`) otomatis akan menggunakan parameter **`closePosition=True`**, selaras dengan standar keamanan API Binance agar posisi tidak berlipat ganda dan berbalik arah *(*rekty*)*.

---

## 🛠 Instalasi dan Konfigurasi

1. Pastikan Anda menginstal *library*:
   `pip install -r requirements.txt` (atau instal `fastapi uvicorn binance-futures-connector supabase python-dotenv pydantic`).

2. Salin rahasia env milik Anda. Atur _API Keys_ pada berkas `.env`:
    ```ini
    BINANCE_API_KEY=KunciBinanceTestnetAnda...
    BINANCE_API_SECRET=RahasiaBinanceAnda...
    SUPABASE_URL=URLSupabaseCloudAnda...
    SUPABASE_KEY=eyJ... (KUNCI SERVICE_ROLE SUPABASE ANDA)
    IS_TESTNET=True
    ```

3. Ekspor & dorong Struktur Data Tabel (Bot_Logs & Trades) dengan `supabase db push`.

4. Start Servis!
   `python main.py`

## ⚠️ Trouble-Shooting Umum!
- **`Error -4061 (Invalid side/Position)`**: Artinya akun Anda berada di dalam mode **Hedge Mode**. Silakan diubah ke tipe **One-Way Mode** pada pegaturan akun *binance testnet* Anda!
- **`Error PGRST204 / 42501 Unauthorized`**: Kunci rahasia pada `.env` Anda keliru. Pastikan mengeklik _Database Secrets_ berlabel `service_role` alih-alih anon publik.
