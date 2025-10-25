import json
import threading
import time
from collections import OrderedDict
from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO, emit
from flask_cors import CORS

import rospy
import rostopic
import rosservice
from rosgraph.masterapi import Master
from roslib.message import get_message_class
import roslib
import actionlib
from actionlib_msgs.msg import GoalStatus

# Global state
subscriptions = {}  # topic_name -> subscriber_object
subscription_lock = threading.Lock()
connected_clients = set()
action_clients = {}  # action_name -> action_client_object
publishers = {}  # topic_name -> publisher_object
publisher_lock = threading.Lock()#!/usr/bin/env python
"""
ROS 1 Web Dashboard Backend
Provides REST API and WebSocket interface for ROS topic visualization
"""



app = Flask(__name__)
app.config['SECRET_KEY'] = 'ros-dashboard-secret'
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# Global state
subscriptions = {}  # topic_name -> subscriber_object
subscription_lock = threading.Lock()
connected_clients = set()
action_clients = {}  # action_name -> action_client_object


def message_to_dict(msg):
    """Convert ROS message to dictionary recursively"""
    if msg is None:
        return None
    
    # Handle primitive types
    if isinstance(msg, (int, float, str, bool)):
        return msg
    
    # Handle lists/tuples
    if isinstance(msg, (list, tuple)):
        return [message_to_dict(item) for item in msg]
    
    # Handle ROS messages (objects with __slots__)
    if hasattr(msg, '__slots__'):
        result = OrderedDict()
        for slot in msg.__slots__:
            try:
                val = getattr(msg, slot)
                result[slot] = message_to_dict(val)
            except AttributeError:
                result[slot] = None
        return result
    
    # Handle ROS Time/Duration
    if hasattr(msg, 'to_sec'):
        return msg.to_sec()
    
    # Default: try to convert to string
    return str(msg)


def get_all_topics():
    """Get list of all available topics with their types"""
    topics = []
    
    try:
        # Get system state from ROS master
        master = Master('/rostopic')
        state = master.getSystemState()
        
        # Publishers: state[0], Subscribers: state[1], Services: state[2]
        publishers_dict = {}
        subscribers_dict = {}
        
        for topic_name, node_list in state[0]:
            publishers_dict[topic_name] = len(node_list)
        
        for topic_name, node_list in state[1]:
            subscribers_dict[topic_name] = len(node_list)
        
        # Get all topic names and types (including subscribed-only topics)
        # Use rostopic.get_topic_type for each topic
        all_topic_names = set()
        
        # Add topics from publishers
        for topic_name, _ in state[0]:
            all_topic_names.add(topic_name)
        
        # Add topics from subscribers
        for topic_name, _ in state[1]:
            all_topic_names.add(topic_name)
        
        # Get type for each topic
        for topic_name in all_topic_names:
            try:
                topic_type, _, _ = rostopic.get_topic_type(topic_name)
                if topic_type:
                    topics.append({
                        'name': topic_name,
                        'type': topic_type,
                        'publishers': publishers_dict.get(topic_name, 0),
                        'subscribers': subscribers_dict.get(topic_name, 0)
                    })
            except:
                # If we can't get the type, skip this topic
                pass
        
        # Sort by name
        topics.sort(key=lambda x: x['name'])
        
    except Exception as e:
        rospy.logerr(f"Error getting topics: {e}")
    
    return topics


def get_all_services():
    """Get list of all available services with their types"""
    services = []
    
    try:
        service_list = rosservice.get_service_list()
        
        for srv_name in service_list:
            try:
                srv_type = rosservice.get_service_type(srv_name)
                services.append({
                    'name': srv_name,
                    'type': srv_type if srv_type else 'unknown'
                })
            except:
                services.append({
                    'name': srv_name,
                    'type': 'unknown'
                })
        
        # Sort by name
        services.sort(key=lambda x: x['name'])
        
    except Exception as e:
        rospy.logerr(f"Error getting services: {e}")
    
    return services


def get_all_actions():
    """Get list of all available actions"""
    actions = []
    
    try:
        # Action servers typically have these topics: /action_name/{goal,cancel,status,feedback,result}
        topics = rospy.get_published_topics()
        action_topics = {}
        
        for topic_name, topic_type in topics:
            if '/goal' in topic_name:
                action_name = topic_name.replace('/goal', '')
                if 'ActionGoal' in topic_type:
                    action_type = topic_type.replace('ActionGoal', 'Action')
                    action_topics[action_name] = action_type
        
        for name, atype in action_topics.items():
            actions.append({
                'name': name,
                'type': atype
            })
        
        actions.sort(key=lambda x: x['name'])
        
    except Exception as e:
        rospy.logerr(f"Error getting actions: {e}")
    
    return actions


def subscribe_to_topic(topic_name, topic_type):
    """Subscribe to a ROS topic and forward messages via WebSocket"""
    with subscription_lock:
        if topic_name in subscriptions:
            rospy.loginfo(f"Already subscribed to {topic_name}")
            return True
        
        try:
            # Get message class from topic type
            msg_class = get_message_class(topic_type)
            
            if msg_class is None:
                rospy.logerr(f"Could not find message class for type: {topic_type}")
                return False
            
            def callback(msg):
                """Callback function for ROS subscriber"""
                try:
                    data = message_to_dict(msg)
                    socketio.emit('topic_data', {
                        'topic': topic_name,
                        'type': topic_type,
                        'data': data,
                        'timestamp': time.time()
                    })
                except Exception as e:
                    rospy.logerr(f"Error processing message from {topic_name}: {e}")
            
            # Create subscriber
            subscriber = rospy.Subscriber(topic_name, msg_class, callback)
            subscriptions[topic_name] = subscriber
            
            rospy.loginfo(f"Subscribed to {topic_name} ({topic_type})")
            return True
            
        except Exception as e:
            rospy.logerr(f"Error subscribing to {topic_name}: {e}")
            return False


def unsubscribe_from_topic(topic_name):
    """Unsubscribe from a ROS topic"""
    with subscription_lock:
        if topic_name in subscriptions:
            try:
                subscriptions[topic_name].unregister()
                del subscriptions[topic_name]
                rospy.loginfo(f"Unsubscribed from {topic_name}")
                return True
            except Exception as e:
                rospy.logerr(f"Error unsubscribing from {topic_name}: {e}")
                return False
        return False


# REST API Endpoints

@app.route('/')
def index():
    """Serve the main dashboard page"""
    return render_template('index.html')


@app.route('/api/topics')
def api_topics():
    """Get all available topics"""
    topics = get_all_topics()
    return jsonify(topics)


@app.route('/api/services')
def api_services():
    """Get all available services"""
    services = get_all_services()
    return jsonify(services)


@app.route('/api/actions')
def api_actions():
    """Get all available actions"""
    actions = get_all_actions()
    return jsonify(actions)


@app.route('/api/discovery')
def api_discovery():
    """Get all ROS entities in one call"""
    return jsonify({
        'topics': get_all_topics(),
        'services': get_all_services(),
        'actions': get_all_actions()
    })


# WebSocket Events

@socketio.on('connect')
def handle_connect(auth=None):
    """Handle client connection"""
    client_id = request.sid
    rospy.loginfo(f"Client connected: {client_id}")
    connected_clients.add(client_id)
    emit('connection_status', {'status': 'connected'})


@socketio.on('disconnect')
def handle_disconnect():
    """Handle client disconnection"""
    client_id = request.sid
    rospy.loginfo(f"Client disconnected: {client_id}")
    if client_id in connected_clients:
        connected_clients.remove(client_id)


@socketio.on('subscribe')
def handle_subscribe(data):
    """Handle subscription request from client"""
    topic_name = data.get('topic')
    topic_type = data.get('type')
    
    if not topic_name or not topic_type:
        emit('error', {'message': 'Missing topic name or type'})
        return
    
    success = subscribe_to_topic(topic_name, topic_type)
    
    if success:
        emit('subscription_status', {
            'topic': topic_name,
            'status': 'subscribed'
        })
    else:
        emit('error', {
            'message': f'Failed to subscribe to {topic_name}'
        })


@socketio.on('unsubscribe')
def handle_unsubscribe(data):
    """Handle unsubscription request from client"""
    topic_name = data.get('topic')
    
    if not topic_name:
        emit('error', {'message': 'Missing topic name'})
        return
    
    success = unsubscribe_from_topic(topic_name)
    
    if success:
        emit('subscription_status', {
            'topic': topic_name,
            'status': 'unsubscribed'
        })
    else:
        emit('error', {
            'message': f'Failed to unsubscribe from {topic_name}'
        })


@socketio.on('call_service')
def handle_call_service(data):
    """Handle service call request from client"""
    service_name = data.get('service')
    service_type = data.get('type')
    request_data = data.get('request', {})
    
    if not service_name or not service_type:
        emit('error', {'message': 'Missing service name or type'})
        return
    
    try:
        # Get service class
        service_class = roslib.message.get_service_class(service_type)
        if service_class is None:
            emit('service_response', {
                'service': service_name,
                'success': False,
                'error': f'Could not find service class for type: {service_type}'
            })
            return
        
        # Wait for service
        rospy.wait_for_service(service_name, timeout=2.0)
        
        # Create service proxy
        service_proxy = rospy.ServiceProxy(service_name, service_class)
        
        # Create request object
        req = service_class._request_class()
        
        # Populate request fields if provided
        if request_data:
            for key, value in request_data.items():
                if hasattr(req, key):
                    setattr(req, key, value)
        
        # Call service
        response = service_proxy(req)
        
        # Convert response to dict
        response_dict = message_to_dict(response)
        
        emit('service_response', {
            'service': service_name,
            'success': True,
            'response': response_dict,
            'timestamp': time.time()
        })
        
        rospy.loginfo(f"Called service {service_name}")
        
    except rospy.ServiceException as e:
        emit('service_response', {
            'service': service_name,
            'success': False,
            'error': f'Service call failed: {str(e)}'
        })
    except Exception as e:
        emit('service_response', {
            'service': service_name,
            'success': False,
            'error': str(e)
        })


@socketio.on('send_action_goal')
def handle_send_action_goal(data):
    """Handle action goal request from client"""
    action_name = data.get('action')
    action_type = data.get('type')
    goal_data = data.get('goal', {})
    
    if not action_name or not action_type:
        emit('error', {'message': 'Missing action name or type'})
        return
    
    try:
        # Get action class
        action_class = roslib.message.get_message_class(action_type)
        if action_class is None:
            emit('action_result', {
                'action': action_name,
                'success': False,
                'error': f'Could not find action class for type: {action_type}'
            })
            return
        
        # Create action client
        if action_name not in action_clients:
            action_clients[action_name] = actionlib.SimpleActionClient(action_name, action_class)
            
            # Wait for server
            if not action_clients[action_name].wait_for_server(rospy.Duration(2.0)):
                emit('action_result', {
                    'action': action_name,
                    'success': False,
                    'error': 'Action server not available'
                })
                del action_clients[action_name]
                return
        
        client = action_clients[action_name]
        
        # Create goal object
        goal = action_class._action_goal._type()
        
        # Populate goal fields if provided
        if goal_data:
            for key, value in goal_data.items():
                if hasattr(goal, key):
                    setattr(goal, key, value)
        
        # Send goal
        client.send_goal(goal)
        
        emit('action_status', {
            'action': action_name,
            'status': 'goal_sent',
            'timestamp': time.time()
        })
        
        rospy.loginfo(f"Sent goal to action {action_name}")
        
        # Wait for result in background thread
        def wait_for_result():
            client.wait_for_result()
            result = client.get_result()
            state = client.get_state()
            
            result_dict = message_to_dict(result) if result else None
            
            socketio.emit('action_result', {
                'action': action_name,
                'success': state == GoalStatus.SUCCEEDED,
                'state': state,
                'result': result_dict,
                'timestamp': time.time()
            })
        
        thread = threading.Thread(target=wait_for_result, daemon=True)
        thread.start()
        
    except Exception as e:
        emit('action_result', {
            'action': action_name,
            'success': False,
            'error': str(e)
        })


@socketio.on('cancel_action_goal')
def handle_cancel_action_goal(data):
    """Handle action goal cancellation"""
    action_name = data.get('action')
    
    if not action_name:
        emit('error', {'message': 'Missing action name'})
        return
    
    if action_name in action_clients:
        try:
            action_clients[action_name].cancel_goal()
            emit('action_status', {
                'action': action_name,
                'status': 'cancelled',
                'timestamp': time.time()
            })
            rospy.loginfo(f"Cancelled action goal for {action_name}")
        except Exception as e:
            emit('error', {'message': f'Failed to cancel goal: {str(e)}'})
    else:
        emit('error', {'message': f'No active action client for {action_name}'})


@socketio.on('publish_message')
def handle_publish_message(data):
    """Handle message publishing to a topic"""
    topic_name = data.get('topic')
    topic_type = data.get('type')
    message_data = data.get('message', {})
    
    if not topic_name or not topic_type:
        emit('error', {'message': 'Missing topic name or type'})
        return
    
    try:
        with publisher_lock:
            # Create publisher if it doesn't exist
            if topic_name not in publishers:
                msg_class = get_message_class(topic_type)
                if msg_class is None:
                    emit('publish_result', {
                        'topic': topic_name,
                        'success': False,
                        'error': f'Could not find message class for type: {topic_type}'
                    })
                    return
                
                publisher = rospy.Publisher(topic_name, msg_class, queue_size=10)
                publishers[topic_name] = publisher
                
                # Give publisher time to connect
                rospy.sleep(0.5)
                rospy.loginfo(f"Created publisher for {topic_name}")
            
            publisher = publishers[topic_name]
        
        # Create message instance
        msg_class = get_message_class(topic_type)
        msg = msg_class()
        
        # Populate message fields from provided data
        rospy.loginfo(f"Publishing to {topic_name}: {message_data}")
        populate_message(msg, message_data)
        
        # Publish message
        publisher.publish(msg)
        
        emit('publish_result', {
            'topic': topic_name,
            'success': True,
            'timestamp': time.time()
        })
        
        rospy.loginfo(f"Published message to {topic_name}: {msg}")
        
    except Exception as e:
        emit('publish_result', {
            'topic': topic_name,
            'success': False,
            'error': str(e)
        })
        rospy.logerr(f"Error publishing to {topic_name}: {e}")
        import traceback
        traceback.print_exc()


def populate_message(msg, data):
    """Recursively populate ROS message fields from dictionary"""
    if not isinstance(data, dict):
        return
    
    for key, value in data.items():
        if not hasattr(msg, key):
            rospy.logwarn(f"Message does not have field: {key}")
            continue
        
        try:
            attr = getattr(msg, key)
            
            # Handle nested messages (objects with __slots__)
            if hasattr(attr, '__slots__') and isinstance(value, dict):
                populate_message(attr, value)
            # Handle lists
            elif isinstance(value, list):
                # Check if it's a list of messages or primitives
                if len(value) > 0 and isinstance(value[0], dict):
                    # List of messages - need to handle differently
                    setattr(msg, key, value)
                else:
                    # List of primitives
                    setattr(msg, key, value)
            # Handle primitive types (int, float, str, bool)
            else:
                setattr(msg, key, value)
                
        except Exception as e:
            rospy.logerr(f"Error setting field {key} to {value}: {e}")
            import traceback
            traceback.print_exc()


@socketio.on('get_message_template')
def handle_get_message_template(data):
    """Get a template/structure for a message type"""
    topic_type = data.get('type')
    
    if not topic_type:
        emit('error', {'message': 'Missing topic type'})
        return
    
    try:
        msg_class = get_message_class(topic_type)
        if msg_class is None:
            emit('message_template', {
                'type': topic_type,
                'success': False,
                'error': f'Could not find message class for type: {topic_type}'
            })
            return
        
        # Create empty message instance
        msg = msg_class()
        
        # Convert to dict to get structure
        template = message_to_dict(msg)
        
        emit('message_template', {
            'type': topic_type,
            'success': True,
            'template': template
        })
        
    except Exception as e:
        emit('message_template', {
            'type': topic_type,
            'success': False,
            'error': str(e)
        })


def main():
    """Main entry point"""
    # Initialize ROS node
    rospy.init_node('ros_web_dashboard', anonymous=True)
    rospy.loginfo("ROS Web Dashboard starting...")
    
    # Start Flask-SocketIO server
    try:
        socketio.run(app, host='0.0.0.0', port=5000, debug=False)
    except KeyboardInterrupt:
        rospy.loginfo("Shutting down...")
    finally:
        # Clean up subscriptions
        with subscription_lock:
            for sub in subscriptions.values():
                sub.unregister()
        rospy.signal_shutdown("Server stopped")


if __name__ == '__main__':
    main()
