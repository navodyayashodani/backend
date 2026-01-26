-- db_commands.sql

-- View all users with details
SELECT 
    id,
    username,
    email,
    first_name || ' ' || last_name as full_name,
    role,
    company_name,
    phone_number,
    is_active,
    date_joined
FROM accounts_user
ORDER BY date_joined DESC;

-- View all tenders with manufacturer info
SELECT 
    t.tender_number,
    t.tender_title,
    t.oil_type,
    t.quantity,
    t.quality_grade,
    t.quality_score,
    t.status,
    u.username as manufacturer,
    u.company_name,
    t.created_at
FROM tenders_tender t
JOIN accounts_user u ON t.manufacturer_id = u.id
ORDER BY t.created_at DESC;

-- View bids with details
SELECT 
    tb.id,
    t.tender_number,
    t.tender_title,
    buyer.username as buyer_name,
    buyer.company_name as buyer_company,
    tb.bid_amount,
    tb.status,
    tb.created_at
FROM tenders_tenderbid tb
JOIN tenders_tender t ON tb.tender_id = t.id
JOIN accounts_user buyer ON tb.buyer_id = buyer.id
ORDER BY tb.created_at DESC;

-- Statistics
SELECT 
    'Total Users' as metric,
    COUNT(*) as count
FROM accounts_user
UNION ALL
SELECT 
    'Manufacturers',
    COUNT(*)
FROM accounts_user
WHERE role = 'manufacturer'
UNION ALL
SELECT 
    'Buyers',
    COUNT(*)
FROM accounts_user
WHERE role = 'buyer'
UNION ALL
SELECT 
    'Active Tenders',
    COUNT(*)
FROM tenders_tender
WHERE status = 'active'
UNION ALL
SELECT 
    'Total Bids',
    COUNT(*)
FROM tenders_tenderbid;