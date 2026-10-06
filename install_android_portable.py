import os
import urllib.request
import zipfile
import subprocess
import shutil
import sys

def download_file(url, dest):
    print(f"Downloading {url}...")
    urllib.request.urlretrieve(url, dest)
    print("Download complete.")

def extract_zip(zip_path, dest_dir):
    print(f"Extracting {zip_path} to {dest_dir}...")
    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        zip_ref.extractall(dest_dir)
    print("Extraction complete.")

def main():
    user_home = os.path.expanduser("~")
    sdk_dir = os.path.join(user_home, "AppData", "Local", "Android", "Sdk")
    java_dir = os.path.join(user_home, "AppData", "Local", "Java")
    
    os.makedirs(sdk_dir, exist_ok=True)
    os.makedirs(java_dir, exist_ok=True)
    
    jdk_zip = os.path.join(java_dir, "jdk.zip")
    sdk_zip = os.path.join(sdk_dir, "cmdline-tools.zip")
    
    # 1. Download OpenJDK 17 Portable
    jdk_url = "https://github.com/adoptium/temurin17-binaries/releases/download/jdk-17.0.11%2B9/OpenJDK17U-jdk_x64_windows_hotspot_17.0.11_9.zip"
    if not os.path.exists(os.path.join(java_dir, "jdk-17.0.11+9")):
        download_file(jdk_url, jdk_zip)
        extract_zip(jdk_zip, java_dir)
        os.remove(jdk_zip)
        
    jdk_home = os.path.join(java_dir, "jdk-17.0.11+9")
    print(f"Java Home configured at: {jdk_home}")
    
    # 2. Download Android Command Line Tools
    sdk_url = "https://dl.google.com/android/repository/commandlinetools-win-11076708_latest.zip"
    if not os.path.exists(os.path.join(sdk_dir, "cmdline-tools", "latest")):
        download_file(sdk_url, sdk_zip)
        extract_zip(sdk_zip, os.path.join(sdk_dir, "cmdline-tools-temp"))
        os.remove(sdk_zip)
        
        # Structure needs to be Sdk/cmdline-tools/latest/
        dest_latest = os.path.join(sdk_dir, "cmdline-tools", "latest")
        os.makedirs(os.path.dirname(dest_latest), exist_ok=True)
        
        # Move files
        src_cmdline = os.path.join(sdk_dir, "cmdline-tools-temp", "cmdline-tools")
        if os.path.exists(dest_latest):
            shutil.rmtree(dest_latest)
        shutil.move(src_cmdline, dest_latest)
        shutil.rmtree(os.path.join(sdk_dir, "cmdline-tools-temp"))
        
    print("Command-line tools configured at Sdk/cmdline-tools/latest.")
    
    # Configure env variables for execution
    env = os.environ.copy()
    env["JAVA_HOME"] = jdk_home
    env["ANDROID_HOME"] = sdk_dir
    # Add java and cmdline-tools paths to PATH
    env["PATH"] = f"{os.path.join(jdk_home, 'bin')};{os.path.join(sdk_dir, 'cmdline-tools', 'latest', 'bin')};{env['PATH']}"
    
    # 3. Configure Flutter Android SDK path
    print("Configuring Flutter SDK path...")
    subprocess.run(["flutter", "config", "--android-sdk", sdk_dir], env=env, shell=True)
    
    # 4. Accept Android licenses
    print("Accepting Android licenses...")
    sdkmanager = os.path.join(sdk_dir, "cmdline-tools", "latest", "bin", "sdkmanager.bat")
    
    # Accept licenses via stdin redirect
    p = subprocess.Popen([sdkmanager, "--licenses", f"--sdk_root={sdk_dir}"], stdin=subprocess.PIPE, env=env, shell=True)
    p.communicate(input=b"y\ny\ny\ny\ny\ny\ny\ny\ny\ny\n")
    
    # 5. Install platform tools and platforms
    print("Installing Android platform tools (SDK 34)...")
    subprocess.run([sdkmanager, "platform-tools", "platforms;android-34", "build-tools;34.0.0", f"--sdk_root={sdk_dir}"], env=env, shell=True)
    
    # 6. Build the APK
    print("Running Flutter Build APK...")
    flutter_app_dir = r"c:\Users\kmoni\Downloads\medi-main-main\medi-main-main\flutter_app"
    
    # Verify licenses with flutter
    p_licenses = subprocess.Popen(["flutter", "doctor", "--android-licenses"], stdin=subprocess.PIPE, env=env, shell=True)
    p_licenses.communicate(input=b"y\ny\ny\ny\ny\ny\ny\ny\ny\ny\n")
    
    build_process = subprocess.run(["flutter", "build", "apk", "--release"], cwd=flutter_app_dir, env=env, shell=True)
    
    if build_process.returncode == 0:
        print("\n==================================================")
        print("SUCCESS: APK built successfully!")
        print(f"APK Path: {os.path.join(flutter_app_dir, 'build', 'app', 'outputs', 'flutter-apk', 'app-release.apk')}")
        print("==================================================")
    else:
        print("\nERROR: Failed to build APK. Check logs above.")

if __name__ == "__main__":
    main()
