# Dockerfile
# Use a lightweight Python base image
FROM python:3.9

# Set the working directory in the container
WORKDIR /app

# Copy the Python application files into the container
COPY src/*.py .

# Expose the port the app runs on
EXPOSE 5000

# Install any required Python dependencies (if any)
# RUN pip install --no-cache-dir your-package-name
RUN pip install requests
RUN pip install flask
RUN pip install schedule

# Set the timezone environment variable
ENV TZ="America/New_York"

# Define the command to run the Python application
CMD ["python", "app.py"]