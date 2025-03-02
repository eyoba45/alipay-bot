
#!/bin/bash
# Run the uptime monitor in the background with nohup
nohup python3 test_bot_uptime.py > uptime_monitor.log 2>&1 &
echo "Uptime monitor started with PID $!"
echo "Check uptime_monitor.log and bot_uptime.log for monitoring information"
