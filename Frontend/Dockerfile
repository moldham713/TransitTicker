# Dockerfile
# Use a lightweight Python base image. No Node.js needed - the "React" page is
# served as static HTML that pulls React/Babel from CDN and JSX-transforms in
# the browser, so there's no npm build step to run in this image.
FROM python:3.9

# Set the working directory in the container
WORKDIR /app

# Copy the Flask server and the static frontend files into the container
COPY server.py .
COPY static ./static

# Install dependencies
RUN pip install flask

# The backend URL the browser should call - override at `docker run` time
# with -e BACKEND_API_URL=http://<host-reachable-backend>:5000 if the backend
# isn't on localhost:5000 from the browser's perspective.
ENV BACKEND_API_URL="http://localhost:5000"

# Expose the port the app runs on
EXPOSE 5001

# Define the command to run the Flask server
CMD ["python", "server.py"]
