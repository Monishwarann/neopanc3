import requests

def test():
    log_id = "u2blg9ydoPM1ie4nudYs"  # The log_id we got from our previous test
    url = f"http://127.0.0.1:5000/api/generate-pdf/{log_id}"
    
    print(f"Hitting Local API /api/generate-pdf/{log_id}: {url}...")
    try:
        response = requests.get(url)
        print(f"Status Code: {response.status_code}")
        if response.status_code == 200:
            print("PDF Downloaded Successfully! Size:", len(response.content), "bytes")
            # Save the PDF to backend directory to verify
            with open("PCRI_Report_Test.pdf", "wb") as f:
                f.write(response.content)
            print("PDF saved as PCRI_Report_Test.pdf")
        else:
            print(f"Error response: {response.text}")
    except Exception as e:
        print(f"Failed to connect: {e}")

if __name__ == "__main__":
    test()
