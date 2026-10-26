const express = require('express');
const mysql = require('mysql2/promise');
const cors = require('cors');
const { v4: uuidv4 } = require('uuid');

const app = express();
const PORT = process.env.PORT || 3000;

app.use(cors());
app.use(express.json());

// MySQL connection pool
const pool = mysql.createPool({
    host: process.env.DB_HOST || 'localhost',
    user: process.env.DB_USER || 'root',
    password: process.env.DB_PASSWORD !== undefined ? process.env.DB_PASSWORD : '#170I@MHUM@N',
    database: process.env.DB_NAME || 'store_inventory',
    waitForConnections: true,
    connectionLimit: 10,
    queueLimit: 0
});

// GET /api/inventory/:barcode
app.get('/api/inventory/:barcode', async (req, res) => {
    try {
        const [rows] = await pool.query('SELECT * FROM inventory WHERE barcode = ?', [req.params.barcode]);
        if (rows.length > 0) {
            res.json(rows[0]);
        } else {
            res.status(404).json({ error: 'Item not found' });
        }
    } catch (err) {
        console.error(err);
        res.status(500).json({ error: 'Database error' });
    }
});

// POST /api/bills - Create pending bill
app.post('/api/bills', async (req, res) => {
    const { staff_username, total_amount, discount_applied, cart_items } = req.body;
    const bill_id = uuidv4();
    try {
        await pool.query(
            `INSERT INTO pending_bills (bill_id, staff_username, total_amount, discount_applied, cart_items) 
             VALUES (?, ?, ?, ?, ?)`,
            [bill_id, staff_username, total_amount, discount_applied || 0, JSON.stringify(cart_items)]
        );
        res.status(201).json({ message: 'Pending bill created', bill_id });
    } catch (err) {
        console.error(err);
        res.status(500).json({ error: 'Database error' });
    }
});

// GET /api/bills/pending
app.get('/api/bills/pending', async (req, res) => {
    try {
        const [rows] = await pool.query("SELECT * FROM pending_bills WHERE status = 'PENDING' ORDER BY created_at ASC");
        res.json(rows);
    } catch (err) {
        console.error(err);
        res.status(500).json({ error: 'Database error' });
    }
});

// POST /api/bills/confirm
app.post('/api/bills/confirm', async (req, res) => {
    const { bill_id } = req.body;
    
    const connection = await pool.getConnection();
    try {
        await connection.beginTransaction();

        // 1. Fetch pending bill
        const [bills] = await connection.query('SELECT * FROM pending_bills WHERE bill_id = ? AND status = "PENDING"', [bill_id]);
        if (bills.length === 0) {
            await connection.rollback();
            return res.status(404).json({ error: 'Pending bill not found' });
        }
        
        const bill = bills[0];
        const cartItems = typeof bill.cart_items === 'string' ? JSON.parse(bill.cart_items) : bill.cart_items;
        
        // 2. Validate stock
        for (const item of cartItems) {
            const [invRows] = await connection.query('SELECT stock_count, name FROM inventory WHERE barcode = ? FOR UPDATE', [item.barcode]);
            if (invRows.length === 0) {
                await connection.rollback();
                return res.status(400).json({ error: `Item ${item.barcode} not found in inventory.` });
            }
            if (invRows[0].stock_count < item.quantity) {
                await connection.rollback();
                return res.status(400).json({ error: `Insufficient stock for ${invRows[0].name}. Available: ${invRows[0].stock_count}, Requested: ${item.quantity}` });
            }
        }
        
        // 3. Deduct stock
        for (const item of cartItems) {
            await connection.query('UPDATE inventory SET stock_count = stock_count - ? WHERE barcode = ?', [item.quantity, item.barcode]);
        }
        
        // 4. Update pending_bills
        await connection.query('UPDATE pending_bills SET status = "COMPLETED" WHERE bill_id = ?', [bill_id]);
        
        // 5. Insert into transactions
        const transaction_id = uuidv4();
        await connection.query(
            `INSERT INTO transactions (transaction_id, staff_username, total_amount, discount_applied, cart_items)
             VALUES (?, ?, ?, ?, ?)`,
            [transaction_id, bill.staff_username, bill.total_amount, bill.discount_applied, JSON.stringify(cartItems)]
        );
        
        await connection.commit();
        res.json({ message: 'Transaction confirmed successfully', transaction_id });
        
    } catch (err) {
        await connection.rollback();
        console.error(err);
        res.status(500).json({ error: 'Transaction failed, rolled back' });
    } finally {
        connection.release();
    }
});

// POST /api/auth/login
app.post('/api/auth/login', (req, res) => {
    const { username } = req.body;
    if (username && username.trim().length > 0) {
        res.json({ message: 'Login successful', username });
    } else {
        res.status(400).json({ error: 'Username required' });
    }
});

// GET /api/inventory (All with optional search)
app.get('/api/inventory', async (req, res) => {
    try {
        let queryStr = 'SELECT * FROM inventory WHERE 1=1';
        let queryParams = [];

        if (req.query.q) {
            queryStr += ' AND (name LIKE ? OR barcode LIKE ?)';
            queryParams.push(`%${req.query.q}%`, `%${req.query.q}%`);
        }
        if (req.query.category && req.query.category !== 'All') {
            queryStr += ' AND category = ?';
            queryParams.push(req.query.category);
        }

        queryStr += ' ORDER BY created_at DESC';

        const [rows] = await pool.query(queryStr, queryParams);
        res.json(rows);
    } catch (err) {
        console.error(err);
        res.status(500).json({ error: 'Database error' });
    }
});

// POST /api/inventory
app.post('/api/inventory', async (req, res) => {
    const { barcode, name, category, price, stock_count, original_price, expiry } = req.body;
    try {
        await pool.query(
            `INSERT INTO inventory (barcode, name, category, price, stock_count, original_price, expiry) 
             VALUES (?, ?, ?, ?, ?, ?, ?)`,
            [barcode, name, category || 'General', price || 0, stock_count || 0, original_price || 0, expiry || 'N/A']
        );
        res.status(201).json({ message: 'Product added successfully' });
    } catch (err) {
        console.error(err);
        if (err.code === 'ER_DUP_ENTRY') {
            res.status(409).json({ error: 'Barcode already exists' });
        } else {
            res.status(500).json({ error: 'Database error' });
        }
    }
});

// PUT /api/inventory/:barcode
app.put('/api/inventory/:barcode', async (req, res) => {
    const { name, category, price, stock_count, original_price, expiry } = req.body;
    try {
        const [result] = await pool.query(
            `UPDATE inventory 
             SET name=?, category=?, price=?, stock_count=?, original_price=?, expiry=? 
             WHERE barcode=?`,
            [name, category, price, stock_count, original_price, expiry, req.params.barcode]
        );
        if (result.affectedRows === 0) {
            return res.status(404).json({ error: 'Product not found' });
        }
        res.json({ message: 'Product updated successfully' });
    } catch (err) {
        console.error(err);
        res.status(500).json({ error: 'Database error' });
    }
});

// DELETE /api/inventory/:barcode
app.delete('/api/inventory/:barcode', async (req, res) => {
    try {
        const [result] = await pool.query('DELETE FROM inventory WHERE barcode=?', [req.params.barcode]);
        if (result.affectedRows === 0) {
            return res.status(404).json({ error: 'Product not found' });
        }
        res.json({ message: 'Product deleted successfully' });
    } catch (err) {
        console.error(err);
        res.status(500).json({ error: 'Database error' });
    }
});

// GET /api/inventory/search
app.get('/api/inventory/search', async (req, res) => {
    const query = req.query.q;
    if (!query) return res.status(400).json({ error: 'Query parameter "q" is required' });
    
    try {
        const [rows] = await pool.query('SELECT * FROM inventory WHERE name LIKE ? OR barcode LIKE ? LIMIT 20', [`%${query}%`, `%${query}%`]);
        res.json(rows);
    } catch (err) {
        console.error(err);
        res.status(500).json({ error: 'Database error' });
    }
});

// GET /api/transactions/:id
app.get('/api/transactions/:id', async (req, res) => {
    try {
        const [rows] = await pool.query('SELECT * FROM transactions WHERE transaction_id = ?', [req.params.id]);
        if (rows.length > 0) {
            res.json(rows[0]);
        } else {
            res.status(404).json({ error: 'Transaction not found' });
        }
    } catch (err) {
        console.error(err);
        res.status(500).json({ error: 'Database error' });
    }
});

// POST /api/transactions/refund
app.post('/api/transactions/refund', async (req, res) => {
    const { transaction_id, items_to_refund, refund_amount } = req.body;
    // items_to_refund is an array of { barcode, quantity }
    
    const connection = await pool.getConnection();
    try {
        await connection.beginTransaction();
        
        // Verify transaction exists
        const [txRows] = await connection.query('SELECT * FROM transactions WHERE transaction_id = ? FOR UPDATE', [transaction_id]);
        if (txRows.length === 0) {
            await connection.rollback();
            return res.status(404).json({ error: 'Transaction not found' });
        }
        
        // Update stock
        for (const item of items_to_refund) {
            await connection.query('UPDATE inventory SET stock_count = stock_count + ? WHERE barcode = ?', [item.quantity, item.barcode]);
        }
        
        // Update transaction refund amount
        await connection.query('UPDATE transactions SET refund_amount = refund_amount + ?, status = "PARTIAL_REFUND" WHERE transaction_id = ?', [refund_amount, transaction_id]);
        
        await connection.commit();
        res.json({ message: 'Refund processed successfully' });
    } catch (err) {
        await connection.rollback();
        console.error(err);
        res.status(500).json({ error: 'Refund transaction failed, rolled back' });
    } finally {
        connection.release();
    }
});

// Bind to 0.0.0.0
app.listen(PORT, '0.0.0.0', () => {
    console.log(`Server listening on http://0.0.0.0:${PORT}`);
});
