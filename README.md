# dynamodb-capacity-reports 

This script will scan your all dynamodb and based on usage of last 15 days it will recommend new provisioned capacity of each dynamodb table along with GSI. After then it will create a report in csv format and upload it to mentioned s3 bucket.




### Prepare System

```bash
cd /home/ec2-user/fastapi/ #consider fastapi is your project directory
virtualenv -p python venv
source venv/bin/activate
```

Our virtualenv is active now run dependent python package using pip.

```bash
(venv) $ pip install -r requirements.txt
```

### Run Projects Locally
**with Uvicorn**
```bash
uvicorn main:app --host 0.0.0.0 --port 8080
```

**with Docker**
```bash
docker run -it -p 8085:80 ishubhoshaha/dynamodb_capacity_reports:latest
```


## Deploy FastApi in Linux AMI

### Configure Nginx

```bash
sudo amazon-linux-extras install nginx1
```

Create nginx configuration file.

```bash
sudo vim /etc/nginx/conf.d/<file_name>.conf
```

Write down following simple nginx configuration file.

```bash
server {
    listen 443;
    server_name <domain-name/IP>;
    keepalive_timeout 5;
}
```

Unlike Debian system in Amazon Linux AMI you don't you have to create symlink to `sites-enabled` directory. To enable your nginx run following command.

```bash
sudo systemctl daemon-reload
sudo systemctl enable nginx.service
sudo systemctl start nginx.service
```

Now Run following command to run our FastApi Server to check our Nginx Configuration working or not.

```bash
gunicorn -w 4 -k uvicorn.workers.UvicornWorker main:app -b 0.0.0.0:8085
```

*Note: While your run this command make sure you enable your virtualenv and and the context path is root directory of your project.*

Remember to change `main:app` on above command as per your project. Now that our application is running and the proxy server is configured properly we should be able to visit the URL and see our application from a browser.

### Configure  service to run our project

Now that our application is deployed and configured properly one last thing to do is to create a service for the Gunicorn server so that it is always running and it automatically starts when the server is rebooted. We will user systemd to create the service.

```bash
sudo vi /etc/systemd/system/<service-name>.service
```

Write following configuration into the file.  And remember to change inside the file as per your project.

```bash
[Unit]
Description=Gunicorn instance to serve my FASTAPI
After=network.target

[Service]
User=ec2-user # you can change as per your project
Group=ec2-user
WorkingDirectory=/home/ec2-user/fastapi/src
Environment="PATH=/home/ec2-user/fastapi/venv/bin"
ExecStart=/home/ec2-user/fastapi/venv/bin/gunicorn -w 4 -k uvicorn.workers.UvicornWorker main:app -b 0.0.0.0:8085

[Install]
WantedBy=multi-user.target
```

Now our service file is ready. Enable service so that this systemd service can run our project.

```bash
sudo systemctl start myapp.service
sudo systemctl enable myapp.service
```