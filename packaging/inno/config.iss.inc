; ============================================================
; Disk Health Report — Installer customization
; Edit this file to brand / tune future releases.
; Version comes from version.py via scripts\sync_version.ps1
; ============================================================

#define MyAppName           "Disk Health Report"
#define MyAppNameShort      "DiskHealthReport"
#define MyAppPublisher      "Disk Health"
#define MyAppExeName        "DiskHealthReport.exe"
#define MyAppURL            "https://github.com/yang532625/Disk-Health-Report"
#define MyAppSupportURL     "https://github.com/yang532625/Disk-Health-Report/issues"
#define MyAppUpdatesURL     "https://github.com/yang532625/Disk-Health-Report/releases"
; Fixed GUID — never change or Windows will treat upgrades as a new app
#define MyAppId             "{{A3F8B2C1-4D5E-6F70-8A9B-0C1D2E3F4A5B}}"

; Install paths
#define MyAppDirName        "DiskHealthReport"
#define MyAppGroupName      "Disk Health Report"
#define MyAppMutex          "DiskHealthReportRunning"
#define MyReportsFolder     "DiskHealthReport"

; Output — real Setup goes to release\
#define MySetupBaseName     "DiskHealthReport_Setup_x64"
#define MySetupOutputDir    "..\..\release"
#define MyAppBinary         "..\..\release\DiskHealthReport.exe"

; Behavior
#define MyMinWindows        "10.0"
; Keep admin: S.M.A.R.T. / disk tools need elevation
#define MyPrivileges        "admin"
