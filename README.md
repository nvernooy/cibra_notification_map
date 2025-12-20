## CIBRA Notification Map Automation

Scripts to download emails from hubspot. Check the contents matching city notification. Process matching emails to extract information for the notification map, and export the information to csv for use in google MyMaps.

### Setup

- install packages from requirements.txt

```
 python3 -m venv venv
 source venv/bin/activate
 pip install -r requirements.txt 
```

Generate OAuth Desktop Credentials
- Go to the Google Cloud Console.
- Navigate to APIs & Services > Credentials.
- Click Create Credentials > OAuth client ID.
- Select Application type: Desktop App.
- Name it and click Create.
- Download the JSON file. Rename it to `credentials.json` and place it in the project folder.

Set tokens and keys in .env and activate

```
source .env
```

Run script using `main.py`

```
python main.py
```