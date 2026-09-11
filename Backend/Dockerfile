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
RUN pip install flask-cors
RUN pip install schedule
RUN pip install gtfs-realtime-bindings

# Set the timezone environment variable
ENV TZ="America/New_York"

# Python fully buffers stdout when it isn't connected to a terminal, which is
# always the case inside a container - print() output can sit in that buffer
# indefinitely instead of reaching `docker logs` until it fills up or the
# process exits. This forces stdout/stderr to be unbuffered so every print()
# (including infrequent ones, like the scheduler's periodic refresh logs)
# shows up immediately.
ENV PYTHONUNBUFFERED=1

# Define the command to run the Python application
CMD ["python", "app.py"]