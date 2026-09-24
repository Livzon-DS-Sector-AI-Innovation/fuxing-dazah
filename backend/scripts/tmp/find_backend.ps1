[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Get-CimInstance Win32_Process |
    Where-Object { $_.Name -match 'python' -and $_.CommandLine -match 'uvicorn' } |
    ForEach-Object {
        "PID=$($_.ProcessId)  启动=$($_.CreationDate.ToString('yyyy-MM-dd HH:mm:ss'))"
        $_.CommandLine
        "---"
    }
