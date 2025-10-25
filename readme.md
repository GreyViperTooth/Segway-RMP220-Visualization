ROS Web Dashboard

A comprehensive web-based interface for ROS 1 that enables real-time monitoring, topic publishing, service calling, and action goal management through a browser interface.

Features

    Real-time Topic Discovery - Automatically detects all available ROS topics, services, and actions
    Topic Subscription - Subscribe to any topic and view live message data in real-time
    Topic Publishing - Publish messages to any topic with automatic template generation
    Service Calls - Call ROS services with custom request parameters
    Action Goals - Send goals to action servers and monitor execution status
    WebSocket Communication - Low-latency bidirectional communication for live data streaming
    Clean Interface - Professional, minimal design focused on functionality
    Multi-client Support - Multiple users can connect simultaneously


Installation
1. Clone or Download the Repository
bash

mkdir ~/ros_web_dashboard
cd ~/ros_web_dashboard

2. Create Project Structure
bash

mkdir templates

3. Install Python Dependencies
bash

pip install -r requirements.txt

4. Source ROS Environment
bash

source /opt/ros/noetic/setup.bash  # Replace 'noetic' with your ROS version

If using a custom workspace:
bash

source ~/catkin_ws/devel/setup.bash

Quick Start
1. Start ROS Core
bash

roscore

2. Launch the Dashboard
bash

cd ~/ros_web_dashboard
python3 app.py

You should see:

[INFO] [timestamp]: ROS Web Dashboard starting...
 * Running on http://0.0.0.0:5000

3. Open Your Browser

Navigate to:

http://localhost:5000

Or from another computer on the same network:

http://<your-machine-ip>:5000

4. Test with TurtleSim
bash

Terminal 1
rosrun turtlesim turtlesim_node

Terminal 2
rosrun turtlesim turtle_teleop_key

Now use the dashboard to:

    Subscribe to /turtle1/pose to see live position data
    Publish to /turtle1/cmd_vel to control the turtle
    Call /spawn service to create a new turtle
