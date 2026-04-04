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

### 4. Batal Semua Order (Sapu Bersih Koin Terkait)
Digunakan jika Anda ingin menembakkan skenario "PANIC CANCEL" secara instan. Mengirim JSON ini ke *endpoint* **`/cancel`** akan otomatis menghapus semua Limit dan Stop Order dari *koin tunggal* yang bersangkutan.

```json
{
  "symbol": "BTCUSDT",
  "cancel_all": true
}
```

### 5. Batal Pesanan Secara Spesifik Saja
Digunakan jika Anda menggunakan *Webhook* secara terukur dan tahu *Order ID* targetnya di Binance. Kirimkan JSON ke *endpoint* **`/cancel`**:

```json
{
  "symbol": "ETHUSDT",
  "order_id": "13018473497"
}
```

### 6. Wallet: Auto-Rebalance BNB
Digunakan untuk mengecek saldo aset stabil Anda (misal: USDT) dan secara cerdas memastikannya memiliki proporsi BNB yang cukup untuk mengamankan diskon *fee* transaksi. Jika persentase BNB kurang dari ambang batas (`min_bnb_percent`), sistem otomatis mengonversi seperlunya (USD ke BNB) menggunakan fitur `Convert` Binance. Kirimkan JSON ke *endpoint* **`/api/wallet/rebalance-bnb`**:

```json
{
  "pass": "RAHASIA_WEBHOOK_ANDA",
  "min_bnb_percent": 5.0,
  "fromAsset": "USDT"
}
```

### 7. Wallet: Update Daily Portfolio
Digunakan untuk merekam *snapshot* kondisi keseimbangan portofolio aset, persentase nilai tukar, dan PnL yang belum direalisasikan (*Unrealized PnL*) ke dalam fungsi logs (*Supabase*) di waktu penutupan hari. Kirimkan JSON ke *endpoint* **`/api/wallet/update-daily`**:

```json
{
  "pass": "@Trashub2025",
  "type": "trigger_update_wallet",
  "wallet_balance_percent": "83.33",
  "targetAsset": "USDC"
}
```

### 8. Order: Place Auto Order (place-order)
Digunakan untuk mengeksekusi *Entry Order* beserta dengan kalkulasi *Risk Management* (Quantity & Leverage) secara terotomatisasi dan dinamis berdasarkan persentase modal terakhir (*single wallet*) di `daily_portfolio`. Endpoint ini juga otomatis memasang setelan *Stop Loss* dan meng-update *Signals* database. Kirimkan JSON ke *endpoint* **`/api/order/place-order`**:

```json
{
  "pass": "RAHASIA_WEBHOOK_ANDA",
  "type": "trigger_order",
  "coin": "BTC",
  "positionSide": "LONG",
  "type_entry": "LIMIT",
  "entry": "60000",
  "tp": "62000",
  "sl": "59000",
  "percent_balance": "10",
  "percent_risk": "2",
  "tp_cancel_percent": "0.5"
}
```
*(Bisa juga mengirimkan `type: "trigger_cancel"` untuk menghapus order dan record secara otomatis).*

### 9. Order: Place Stop Auto Order (place-stop-auto)
Mirip dengan `place-order`, namun digunakan jika *Entry* menggunakan skenario *Breakout/Breakdown* (`STOP_MARKET`) dan parameter TP & SL didefinisikan menggunakan ukuran *persentase*. TP dan SL akan tertahan sementara waktu dan baru diinjeksi via *WebSocket* saat Entry tereksekusi. Kirimkan JSON ke *endpoint* **`/api/order/place-stop-auto`**:

```json
{
  "pass": "RAHASIA_WEBHOOK_ANDA",
  "type": "trigger_order",
  "coin": "ETH",
  "positionSide": "LONG",
  "entry": "3500",
  "tp_percent": "5",
  "sl_percent": "2",
  "percent_balance": "15",
  "percent_risk": "1"
}
```

> **INFO:** Order TP (`LIMIT`) akan otomatis dijalankan dengan setelan **`reduceOnly=True`**. Sedangkan untuk SL (`STOP_MARKET`) otomatis akan dieksekusi persis sama dengan _reduce-only limit_, selaras dengan standar pembaruan keamanan API Binance (tanpa menyentuh `/algoOrder` _rules_ khusus) agar posisi tidak berlipat ganda _(*rekty*)_.

---

## 🛠 Instalasi dan Konfigurasi

1. (Penting jika baru pertama kali) Buat *Virtual Environment*:
    ```bash
    python3 -m venv venv
    ```

2. Salin rahasia env milik Anda. Atur _API Keys_ pada berkas `.env` (Bisa menggunakan referensi `.env.example`):
    ```ini
    BINANCE_API_KEY=KunciBinanceTestnetAnda...
    BINANCE_API_SECRET=RahasiaBinanceAnda...
    SUPABASE_URL=URLSupabaseCloudAnda...
    SUPABASE_KEY=eyJ... (KUNCI SERVICE_ROLE SUPABASE ANDA)
    IS_TESTNET=True
    WEBHOOK_SECRET=RAHASIA_WEBHOOK_ANDA
    ```

3. Ekspor & dorong Struktur Data Tabel (Bot_Logs & Trades) dengan `supabase db push`.

## ▶️ Cara Menjalankan Bot

Pastikan Anda memasukkan 3 perintah ini secara berurutan di terminal setiap kali ingin menyalakan proses algoritma bot:

```bash
# 1. Mengaktifkan Virtual Environment (Status Aktif = Ada teks '(venv)')
source venv/bin/activate

# 2. (Opsional) Memastikan semua paket sistem sudah terinstal di venv
pip3 install -r requirements.txt

# 3. Menjalankan Bot!
python3 main.py
```

*Jika Anda ingin menyalakannya menggunakan uvicorn, di Langkah ke-3 gunakan perintah:* `uvicorn main:app --host 0.0.0.0 --port 8000 --reload`
*Setelah server menyala, dokumentasi UI Swagger API bot Anda bisa diakses pada:* `http://127.0.0.1:8000/docs`


## ⚠️ Trouble-Shooting Umum!
- **`Error -4061 (Invalid side/Position)`**: Artinya akun Anda berada di dalam mode **Hedge Mode**. Silakan diubah ke tipe **One-Way Mode** pada pegaturan akun *binance testnet* Anda!
- **`Error PGRST204 / 42501 Unauthorized`**: Kunci rahasia pada `.env` Anda keliru. Pastikan mengeklik _Database Secrets_ berlabel `service_role` alih-alih anon publik.
