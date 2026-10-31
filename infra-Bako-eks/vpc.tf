resource "aws_vpc" "bako" {
  cidr_block = "10.0.0.0/16"

  tags = {
    Name = "bako-vpc"
  }
}

# Public subnets: the internet-facing load balancer is placed here.
# The tag kubernetes.io/role/elb = 1 is how the AWS Load Balancer Controller finds them.
resource "aws_subnet" "public_a" {
  vpc_id            = aws_vpc.bako.id
  cidr_block        = "10.0.1.0/24"
  availability_zone = "eu-north-1a"

  tags = {
    Name                                        = "bako-public-a"
    "kubernetes.io/role/elb"                    = "1"
    "kubernetes.io/cluster/${var.cluster_name}" = "shared"
  }
}

# Private subnets: nodes and pods live here. internal-elb is for internal load balancers.
resource "aws_subnet" "private_a" {
  vpc_id            = aws_vpc.bako.id
  cidr_block        = "10.0.2.0/24"
  availability_zone = "eu-north-1a"

  tags = {
    Name                                        = "bako-private-a"
    "kubernetes.io/role/internal-elb"           = "1"
    "kubernetes.io/cluster/${var.cluster_name}" = "shared"
  }
}

resource "aws_subnet" "public_b" {
  vpc_id            = aws_vpc.bako.id
  cidr_block        = "10.0.3.0/24"
  availability_zone = "eu-north-1b"

  tags = {
    Name                                        = "bako-public-b"
    "kubernetes.io/role/elb"                    = "1"
    "kubernetes.io/cluster/${var.cluster_name}" = "shared"
  }
}

resource "aws_subnet" "private_b" {
  vpc_id            = aws_vpc.bako.id
  cidr_block        = "10.0.4.0/24"
  availability_zone = "eu-north-1b"

  tags = {
    Name                                        = "bako-private-b"
    "kubernetes.io/role/internal-elb"           = "1"
    "kubernetes.io/cluster/${var.cluster_name}" = "shared"
  }
}
