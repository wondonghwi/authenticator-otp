-- The installer replaces these placeholders with escaped AppleScript strings.
property appTitle : __APP_NAME__
property pythonPath : __PYTHON_PATH__
property serviceName : __SERVICE__
property accountName : __ACCOUNT__

on run
	set appPath to POSIX path of (path to me)
	set scriptPath to appPath & "Contents/Resources/auth-otp.py"
	set shellCommand to quoted form of pythonPath & " " & quoted form of scriptPath & " --service " & quoted form of serviceName & " --account " & quoted form of accountName & " --quiet"
	try
		do shell script shellCommand
		display notification "OTP copied to clipboard." with title appTitle
	on error
		display dialog "Could not copy OTP. Check the Keychain item name, account and access permission. Run the CLI with --check for details." buttons {"OK"} default button "OK" with icon stop
	end try
end run
