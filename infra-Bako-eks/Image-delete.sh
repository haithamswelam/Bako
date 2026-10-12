echo "== Hi this to delete the image after terraform destroy =="
echo
echo
echo "get the images ... for froentend"
aws ecr list-images --repository-name bako-frontend --query 'imageIds[*]' --output json > frontend-images.json
echo
echo "delete the images .. for frontend"
aws ecr batch-delete-image --repository-name bako-frontend --image-ids file://frontend-images.json
echo
echo
echo "get the images ... for backend"
aws ecr list-images --repository-name bako-backend --query 'imageIds[*]' --output json > backend-images.json
echo
echo "delete the images .. for backend"
aws ecr batch-delete-image --repository-name bako-backend --image-ids file://backend-images.json
echo
echo
echo "run terraform destroy again"
terraform destroy 