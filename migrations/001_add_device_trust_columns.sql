-- ============================================================================
-- Idempotent T-SQL Migration Script: Add mTLS Device Trust Columns
-- Target Table: dbo.FieldAttendanceLogs
-- SQL Server Version: MSSQL / T-SQL
-- ============================================================================

IF NOT EXISTS (
    SELECT 1 FROM sys.columns 
    WHERE object_id = OBJECT_ID(N'[dbo].[FieldAttendanceLogs]') 
      AND name = N'DeviceTrustStatus'
)
BEGIN
    ALTER TABLE [dbo].[FieldAttendanceLogs]
    ADD [DeviceTrustStatus] NVARCHAR(50) NULL,
        [DeviceCertificateDN] NVARCHAR(255) NULL,
        [DeviceCertificateSerial] NVARCHAR(64) NULL,
        [IsTrustedDevice] BIT NOT NULL CONSTRAINT DF_Attendance_IsTrustedDevice DEFAULT 0;

    PRINT 'Device trust columns successfully added to FieldAttendanceLogs table.';
END
ELSE
BEGIN
    PRINT 'Device trust columns already exist in FieldAttendanceLogs table.';
END
GO
