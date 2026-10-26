const sqlite3 = require('sqlite3').verbose();
const mysql = require('mysql2/promise');
const fs = require('fs');
const path = require('path');

// 1. Setup MySQL connection
// Note: Hardcoded for localhost based on earlier phases.
const mysqlConfig = {
    host: process.env.DB_HOST || 'localhost',
    user: process.env.DB_USER || 'root',
    password: process.env.DB_PASSWORD !== undefined ? process.env.DB_PASSWORD : '#170I@MHUM@N',
    database: process.env.DB_NAME || 'store_inventory'
};

// 2. Find the SQLite file
const potentialPaths = [
    path.join(__dirname, '..', 'inventory.db'),
    path.join(__dirname, '..', 'store.db'),
    path.join(__dirname, 'inventory.db'),
    path.join(__dirname, 'store.db')
];

let sqlitePath = null;
for (const p of potentialPaths) {
    if (fs.existsSync(p)) {
        sqlitePath = p;
        break;
    }
}

if (!sqlitePath) {
    console.error("❌ Could not find the SQLite database file in any of the standard locations.");
    console.error("Searched paths:", potentialPaths);
    process.exit(1);
}

console.log(`✅ Found SQLite database at: ${sqlitePath}`);

async function migrate() {
    let mysqlConn = null;
    let sqliteDb = null;

    try {
        mysqlConn = await mysql.createConnection(mysqlConfig);
        console.log("✅ Connected to MySQL store_inventory.");

        // 3. Ensure the schema has original_price and expiry
        console.log("⚙️  Checking MySQL schema...");
        try {
            await mysqlConn.query(`ALTER TABLE inventory ADD COLUMN original_price DECIMAL(10,2) DEFAULT 0.00;`);
            console.log("   Added original_price column.");
        } catch (err) {
            if (err.code !== 'ER_DUP_FIELDNAME') throw err;
        }

        try {
            await mysqlConn.query(`ALTER TABLE inventory ADD COLUMN expiry VARCHAR(50) DEFAULT 'N/A';`);
            console.log("   Added expiry column.");
        } catch (err) {
            if (err.code !== 'ER_DUP_FIELDNAME') throw err;
        }

        // 4. Open SQLite
        sqliteDb = new sqlite3.Database(sqlitePath, sqlite3.OPEN_READONLY);
        
        // Read all products from SQLite
        const products = await new Promise((resolve, reject) => {
            sqliteDb.all('SELECT * FROM products', (err, rows) => {
                if (err) reject(err);
                else resolve(rows);
            });
        });

        console.log(`📦 Found ${products.length} products in SQLite. Starting migration...`);

        // 5. Batch Upsert to MySQL
        let successCount = 0;
        
        for (const item of products) {
            // Data Coercion & NULL handling
            const barcode = item.barcode ? String(item.barcode) : 'UNKNOWN';
            const name = item.name ? String(item.name) : 'Unnamed Product';
            const category = item.category ? String(item.category) : 'General';
            
            // Handle numeric casting (dynamic SQLite to strict MySQL)
            const price = parseFloat(item.price) || 0.00;
            const original_price = parseFloat(item.original_price) || 0.00;
            const stock_count = parseInt(item.quantity, 10) || 0;
            const expiry = item.expiry ? String(item.expiry) : 'N/A';

            const query = `
                INSERT INTO inventory (barcode, name, category, price, stock_count, original_price, expiry)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON DUPLICATE KEY UPDATE 
                    name = VALUES(name),
                    category = VALUES(category),
                    price = VALUES(price),
                    stock_count = VALUES(stock_count),
                    original_price = VALUES(original_price),
                    expiry = VALUES(expiry)
            `;

            try {
                await mysqlConn.query(query, [barcode, name, category, price, stock_count, original_price, expiry]);
                successCount++;
            } catch (err) {
                console.error(`❌ Failed to migrate product ${barcode}:`, err.message);
            }
        }

        console.log(`\n🎉 Migration Complete! Successfully migrated ${successCount}/${products.length} products to MySQL.`);

    } catch (err) {
        console.error("❌ Migration failed:", err);
    } finally {
        if (mysqlConn) await mysqlConn.end();
        if (sqliteDb) {
            sqliteDb.close();
        }
    }
}

migrate();
