resource "aws_ecs_cluster" "main" {
  name = "${var.project_name}-cluster"

  setting {
    name  = "containerInsights"
    value = "disabled" # extra cost for cluster-level CloudWatch metrics not needed here
  }
}

resource "aws_cloudwatch_log_group" "backend" {
  name              = "/ecs/${var.project_name}-backend"
  retention_in_days = 14
}

resource "aws_cloudwatch_log_group" "frontend" {
  name              = "/ecs/${var.project_name}-frontend"
  retention_in_days = 14
}

# --- Task execution role: lets Fargate pull the image from ECR and ship logs
# to CloudWatch on the task's behalf. This is distinct from a task role
# (which grants the *application code* AWS API access) - the frontend still
# calls no AWS API and has no task role, but the backend now reads/writes
# the users table (see below), so it gets one.
resource "aws_iam_role" "ecs_task_execution" {
  name = "${var.project_name}-ecs-task-execution"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "ecs_task_execution" {
  role       = aws_iam_role.ecs_task_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# --- Backend task role: what the backend's own application code (not the
# Fargate agent) is allowed to do, scoped to exactly the one table it needs.
resource "aws_iam_role" "backend_task" {
  name = "${var.project_name}-backend-task"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "backend_task_dynamodb" {
  name = "${var.project_name}-backend-dynamodb"
  role = aws_iam_role.backend_task.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid    = "UsersTableAccess"
      Effect = "Allow"
      Action = [
        "dynamodb:GetItem",
        "dynamodb:PutItem",
        "dynamodb:UpdateItem",
        "dynamodb:Query",
      ]
      Resource = [
        aws_dynamodb_table.users.arn,
        "${aws_dynamodb_table.users.arn}/index/*", # required for Query against the device_token GSI
      ]
    }]
  })
}

# --- Security group: tasks only ever accept traffic from the ALB, never
# directly from the internet (only the ALB's own SG is reachable publicly).
resource "aws_security_group" "ecs_tasks" {
  name        = "${var.project_name}-ecs-tasks-sg"
  description = "Allow inbound traffic from the ALB only."
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "From ALB"
    from_port       = 0
    to_port         = 65535
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${var.project_name}-ecs-tasks-sg"
  }
}

# ============================= Backend service =============================

# Signs the backend's session cookies (see Backend/src/auth.py). Generated
# once and stored in Terraform state rather than a secrets manager - a
# pragmatic choice at this project's scale, since a leaked value only lets
# someone forge a session for a user_id they'd already have to know, not
# recover any stored credential. AWS Secrets Manager would be the upgrade
# path if that trade-off ever stops being acceptable.
resource "random_password" "session_secret" {
  length  = 48
  special = false
}

resource "aws_ecs_task_definition" "backend" {
  family                   = "${var.project_name}-backend"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.backend_cpu
  memory                   = var.backend_memory
  execution_role_arn       = aws_iam_role.ecs_task_execution.arn
  task_role_arn            = aws_iam_role.backend_task.arn

  container_definitions = jsonencode([{
    name      = "backend"
    image     = "${aws_ecr_repository.backend.repository_url}:${var.backend_image_tag}"
    essential = true
    portMappings = [{
      containerPort = 5000
      protocol      = "tcp"
    }]
    environment = [
      {
        # Fargate doesn't inject this automatically the way some other AWS
        # compute does - boto3 needs it explicitly to know which region's
        # DynamoDB endpoint to call.
        name  = "AWS_REGION"
        value = var.aws_region
      },
      {
        name  = "DYNAMODB_TABLE_NAME"
        value = aws_dynamodb_table.users.name
      },
      {
        name  = "GOOGLE_CLIENT_ID"
        value = var.google_client_id
      },
      {
        name  = "SESSION_SECRET_KEY"
        value = random_password.session_secret.result
      },
      {
        # CORS needs one explicit allowed origin (not "*") to support
        # credentialed requests - see Backend/src/app.py. The frontend's
        # public URL is the ALB's own DNS name on the default HTTP port.
        name  = "FRONTEND_ORIGIN"
        value = "http://${aws_lb.main.dns_name}"
      },
    ]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.backend.name
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "backend"
      }
    }
  }])
}

resource "aws_ecs_service" "backend" {
  name            = "${var.project_name}-backend"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.backend.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = aws_subnet.public[*].id
    security_groups  = [aws_security_group.ecs_tasks.id]
    assign_public_ip = true # tasks live in public subnets - see the note in vpc.tf
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.backend.arn
    container_name   = "backend"
    container_port   = 5000
  }

  depends_on = [aws_lb_listener.backend]

  lifecycle {
    # CI deploys new images by pushing ":latest" and running
    # `aws ecs update-service --force-new-deployment`, not by changing
    # var.backend_image_tag and re-running `terraform apply`. Without this,
    # a routine apply (e.g. tweaking an unrelated variable) would silently
    # roll the service back to whichever image tag was last applied here.
    ignore_changes = [task_definition]
  }
}

# ============================= Frontend service =============================

resource "aws_ecs_task_definition" "frontend" {
  family                   = "${var.project_name}-frontend"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.frontend_cpu
  memory                   = var.frontend_memory
  execution_role_arn       = aws_iam_role.ecs_task_execution.arn

  container_definitions = jsonencode([{
    name      = "frontend"
    image     = "${aws_ecr_repository.frontend.repository_url}:${var.frontend_image_tag}"
    essential = true
    portMappings = [{
      containerPort = 5001
      protocol      = "tcp"
    }]
    environment = [
      {
        name = "BACKEND_API_URL"
        # Must be reachable from the *browser*, not just from inside the VPC -
        # same constraint the frontend was already built around locally (see
        # Frontend/server.py). The ALB's own public DNS name on the backend
        # listener's port satisfies that.
        value = "http://${aws_lb.main.dns_name}:8080"
      },
      {
        name  = "GOOGLE_CLIENT_ID"
        value = var.google_client_id
      },
    ]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.frontend.name
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "frontend"
      }
    }
  }])
}

resource "aws_ecs_service" "frontend" {
  name            = "${var.project_name}-frontend"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.frontend.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = aws_subnet.public[*].id
    security_groups  = [aws_security_group.ecs_tasks.id]
    assign_public_ip = true
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.frontend.arn
    container_name   = "frontend"
    container_port   = 5001
  }

  depends_on = [aws_lb_listener.frontend]

  lifecycle {
    ignore_changes = [task_definition]
  }
}
