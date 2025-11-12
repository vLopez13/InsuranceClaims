
CREATE TABLE Claims (
    -- Primary Key for the Claims table
    ClaimID INT AUTO_INCREMENT PRIMARY KEY,

    -- ID of the specific insurance company/payer.
    -- Needed for routing and reconciliation.
    PayerID VARCHAR(50) NOT NULL COMMENT 'ID of the specific insurance company/payer.',

    -- ID of the human who made the final decision (if manual).
    -- Audit and accountability.
    ReviewerUserID INT COMMENT 'ID of the human who made the final decision (NULL if automated).',

    -- Standard industry code if the claim is denied (e.g., CO-18).
    -- Essential for denial letters and appeals processing.
    RejectionCode VARCHAR(10) COMMENT 'Denial code if applicable (NULL otherwise).',

    -- The final amount the system approves for payment.
    -- Financial tracking and payment initiation.
    ApprovedAmount DECIMAL(10, 2) NOT NULL DEFAULT 0.00 COMMENT 'The final approved amount for payment.',

    -- e.g., 'Normal', 'Urgent', 'Stat'. Prioritizing claims for human reviewers.
    ClaimPriority VARCHAR(20) NOT NULL DEFAULT 'Normal' COMMENT 'Priority level for review (Normal, Urgent, Stat).',

    -- Flag indicating if the claim was processed fully by the automation system.
    AutomationFlag BOOLEAN NOT NULL DEFAULT FALSE COMMENT 'TRUE if fully processed by automation; FALSE otherwise.'
);

-- Example of adding an index for faster lookups based on Payer
CREATE INDEX idx_payer_id ON Claims (PayerID);

-- Example of adding an index for faster lookups based on Priority
CREATE INDEX idx_claim_priority ON Claims (ClaimPriority);