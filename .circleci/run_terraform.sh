# Install terraform
cd
wget https://releases.hashicorp.com/terraform/0.11.3/terraform_0.11.3_linux_amd64.zip
unzip terraform_0.11.3_linux_amd64.zip
sudo mv terraform /usr/local/bin/

cd ~/refinebio/infrastructure
terraform init

TF_VAR_user=deploy
TV_VAR_stage=production
BUCKET_NAME=refinebio-tfstate-${TF_VAR_user}-${TF_VAR_stage}

# Download encrypted tfstate files from S3
aws s3 cp s3://$BUCKET_NAME/$TFSTATE.enc .
aws s3 cp s3://$BUCKET_NAME/$TFSTATE_BAK.enc .

# Decrypt tfstate files
openssl aes-256-cbc -d -in $TFSTATE.enc -out $TFSTATE -k $OPENSSL_KEY
openssl aes-256-cbc -d -in $TFSTATE_BAK.enc -out $TFSTATE_BAK -k $OPENSSL_KEY

# New deployment
./deploy.sh

# Encrypt new tfstate files
openssl aes-256-cbc -e -in $TFSTATE -out $TFSTATE.enc -k $OPENSSL_KEY
openssl aes-256-cbc -e -in $TFSTATE_BAK -out $TFSTATE_BAK.enc -k $OPENSSL_KEY

# Upload encrypted tfstate files back to S3
aws s3 cp $TFSTATE.enc s3://$BUCKET_NAME/
aws s3 cp $TFSTATE_BAK.enc s3://$BUCKET_NAME/