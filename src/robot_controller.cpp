#include <rclcpp/rclcpp.hpp>
#include <std_msgs/msg/string.hpp>
#include <sensor_msgs/msg/joint_state.hpp>
#include <moveit/move_group_interface/move_group_interface.h>
#include <moveit/robot_state/robot_state.h>
#include <moveit/robot_trajectory/robot_trajectory.h>
#include <tf2_ros/transform_listener.h>
#include <tf2_ros/buffer.h>
#include <tf2_geometry_msgs/tf2_geometry_msgs.hpp>
#include <nlohmann/json.hpp>

using json = nlohmann::json;
using namespace std::chrono_literals;

class RobotController : public rclcpp::Node
{
public:
    RobotController() : Node("robot_controller")
    {
        RCLCPP_INFO(this->get_logger(), "Robot Controller created");
        tf_buffer_ = std::make_unique<tf2_ros::Buffer>(this->get_clock());
        tf_listener_ = std::make_shared<tf2_ros::TransformListener>(*tf_buffer_);
    }

    void initialize()
    {
        auto node_ptr = this->shared_from_this();

        left_arm_ = std::make_shared<moveit::planning_interface::MoveGroupInterface>(
            node_ptr, "arm_left");
        right_arm_ = std::make_shared<moveit::planning_interface::MoveGroupInterface>(
            node_ptr, "arm_right");

        left_arm_->setPlanningTime(60.0);
        left_arm_->setMaxVelocityScalingFactor(0.2);
        left_arm_->setMaxAccelerationScalingFactor(0.2);
        left_arm_->setNumPlanningAttempts(50);
        left_arm_->setPoseReferenceFrame("world");
        left_arm_->setGoalTolerance(0.01);
        left_arm_->setGoalOrientationTolerance(0.05);

        right_arm_->setPlanningTime(60.0);
        right_arm_->setMaxVelocityScalingFactor(0.2);
        right_arm_->setMaxAccelerationScalingFactor(0.2);
        right_arm_->setNumPlanningAttempts(50);
        right_arm_->setPoseReferenceFrame("world");
        right_arm_->setGoalTolerance(0.01);
        right_arm_->setGoalOrientationTolerance(0.05);

        RCLCPP_INFO(this->get_logger(), "Left arm end effector: %s",
            left_arm_->getEndEffectorLink().c_str());
        RCLCPP_INFO(this->get_logger(), "Right arm end effector: %s",
            right_arm_->getEndEffectorLink().c_str());

        joint_state_sub_ = this->create_subscription<sensor_msgs::msg::JointState>(
            "joint_states", 10,
            std::bind(&RobotController::joint_state_callback, this, std::placeholders::_1));

        command_sub_ = this->create_subscription<std_msgs::msg::String>(
            "robot_command", 10,
            std::bind(&RobotController::command_callback, this, std::placeholders::_1));

        RCLCPP_INFO(this->get_logger(), "Robot Controller initialized and ready!");
    }

private:
    void joint_state_callback(const sensor_msgs::msg::JointState::SharedPtr msg)
    {
        std::lock_guard<std::mutex> lock(joint_state_mutex_);
        latest_joint_state_ = *msg;
        got_joint_state_ = true;
    }

    geometry_msgs::msg::Pose getPoseFromTF(const std::string& frame)
    {
        geometry_msgs::msg::Pose pose;
        try {
            auto transform = tf_buffer_->lookupTransform(
                "world", frame, tf2::TimePointZero,
                tf2::Duration(std::chrono::seconds(1)));

            pose.position.x = transform.transform.translation.x;
            pose.position.y = transform.transform.translation.y;
            pose.position.z = transform.transform.translation.z;
            pose.orientation = transform.transform.rotation;

            return pose;

        } catch (const tf2::TransformException& ex) {
            RCLCPP_ERROR(this->get_logger(), "TF error for %s: %s", frame.c_str(), ex.what());
            return pose;
        }
    }

    void command_callback(const std_msgs::msg::String::SharedPtr msg)
    {
        RCLCPP_INFO(this->get_logger(), "Received command: %s", msg->data.c_str());

        try {
            auto cmd = json::parse(msg->data);
            std::string action = cmd["action"];

            if (action == "move_cartesian") {
                move_cartesian(cmd);
            } else if (action == "move_joint") {
                move_joint(cmd);
            } else if (action == "home") {
                home(cmd);
            } else if (action == "get_status") {
                get_status(cmd);
            } else {
                RCLCPP_WARN(this->get_logger(), "Unknown action: %s", action.c_str());
            }
        } catch (const json::exception& e) {
            RCLCPP_ERROR(this->get_logger(), "JSON parse error: %s", e.what());
        }
    }

    std::vector<double> get_current_joints(const std::string& arm)
    {
        std::lock_guard<std::mutex> lock(joint_state_mutex_);

        std::vector<double> joints;
        std::vector<std::string> joint_names;

        if (arm == "left") {
            joint_names = {
                "elfin_joint1_left", "elfin_joint2_left", "elfin_joint3_left",
                "elfin_joint4_left", "elfin_joint5_left", "elfin_joint6_left"
            };
        } else {
            joint_names = {
                "elfin_joint1_right", "elfin_joint2_right", "elfin_joint3_right",
                "elfin_joint4_right", "elfin_joint5_right", "elfin_joint6_right"
            };
        }

        for (const auto& name : joint_names) {
            for (size_t i = 0; i < latest_joint_state_.name.size(); ++i) {
                if (latest_joint_state_.name[i] == name) {
                    joints.push_back(latest_joint_state_.position[i]);
                    break;
                }
            }
        }

        return joints;
    }

    void move_joint(const json& cmd)
    {
        std::string arm = cmd["arm"];
        int joint = cmd["joint"];
        double value = cmd["value"];
        std::string type = cmd.value("type", "absolute");

        RCLCPP_INFO(this->get_logger(), "move_joint: arm=%s, joint=%d, value=%.3f, type=%s",
            arm.c_str(), joint, value, type.c_str());

        if (!got_joint_state_) {
            RCLCPP_ERROR(this->get_logger(), "No joint state received yet!");
            return;
        }

        auto& move_group = (arm == "left") ? *left_arm_ : *right_arm_;
        std::vector<double> current_joints = get_current_joints(arm);

        if (joint < 1 || joint > 6) {
            RCLCPP_ERROR(this->get_logger(), "Invalid joint number: %d", joint);
            return;
        }

        if (type == "delta") {
            current_joints[joint - 1] += value;
        } else {
            current_joints[joint - 1] = value;
        }

        move_group.setJointValueTarget(current_joints);

        moveit::planning_interface::MoveGroupInterface::Plan plan;
        if (move_group.plan(plan) == moveit::core::MoveItErrorCode::SUCCESS) {
            RCLCPP_INFO(this->get_logger(), "Planning successful! Executing...");
            move_group.execute(plan);
            RCLCPP_INFO(this->get_logger(), "Execution complete!");
        } else {
            RCLCPP_ERROR(this->get_logger(), "Planning failed!");
        }
    }

    void move_cartesian(const json& cmd)
    {
        std::string arm = cmd["arm"];
        double x = cmd.value("x", 0.0);
        double y = cmd.value("y", 0.0);
        double z = cmd.value("z", 0.0);
        bool relative = cmd.value("relative", false);

        RCLCPP_INFO(this->get_logger(), "move_cartesian: arm=%s, x=%.3f, y=%.3f, z=%.3f, relative=%d",
            arm.c_str(), x, y, z, relative);

        auto& move_group = (arm == "left") ? *left_arm_ : *right_arm_;
        std::string end_effector = (arm == "left") ? "elfin_link6_left" : "elfin_link6_right";

        // 获取当前位姿作为起点
        auto current_pose = getPoseFromTF(end_effector);

        // 计算目标位姿
        geometry_msgs::msg::Pose target_pose;
        if (relative) {
            target_pose = current_pose;
            target_pose.position.x += x;
            target_pose.position.y += y;
            target_pose.position.z += z;
        } else {
            target_pose.position.x = x;
            target_pose.position.y = y;
            target_pose.position.z = z;
            target_pose.orientation = current_pose.orientation;
        }

        RCLCPP_INFO(this->get_logger(), "Target: [%.3f, %.3f, %.3f]",
            target_pose.position.x, target_pose.position.y, target_pose.position.z);

        // 构建路径点：起点 → 终点（直线路径）
        std::vector<geometry_msgs::msg::Pose> waypoints;
        waypoints.push_back(current_pose);
        waypoints.push_back(target_pose);

        // 使用 computeCartesianPath 规划直线运动
        moveit_msgs::msg::RobotTrajectory trajectory;
        double fraction = move_group.computeCartesianPath(
            waypoints,
            0.01,   // eef_step: 步长 1cm
            0.0,    // jump_threshold: 0 = 不检测跳跃
            trajectory,
            true    // avoid_collisions
        );

        RCLCPP_INFO(this->get_logger(), "Cartesian path coverage: %.2f%%", fraction * 100.0);

        if (fraction >= 0.9) {
            RCLCPP_INFO(this->get_logger(), "Executing Cartesian path...");
            moveit::planning_interface::MoveGroupInterface::Plan plan;
            plan.trajectory_ = trajectory;
            move_group.execute(plan);
            RCLCPP_INFO(this->get_logger(), "Execution complete!");
        } else {
            RCLCPP_ERROR(this->get_logger(), "Cartesian path planning failed! Coverage: %.2f%%", fraction * 100.0);
        }
    }

    void home(const json& cmd)
    {
        std::string arm = cmd["arm"];
        RCLCPP_INFO(this->get_logger(), "home: arm=%s", arm.c_str());

        auto& move_group = (arm == "left") ? *left_arm_ : *right_arm_;

        std::vector<double> home_joints = {0.0, 0.0, 0.0, 0.0, 0.0, 0.0};
        move_group.setJointValueTarget(home_joints);

        moveit::planning_interface::MoveGroupInterface::Plan plan;
        if (move_group.plan(plan) == moveit::core::MoveItErrorCode::SUCCESS) {
            RCLCPP_INFO(this->get_logger(), "Planning successful! Executing...");
            move_group.execute(plan);
            RCLCPP_INFO(this->get_logger(), "Execution complete!");
        } else {
            RCLCPP_ERROR(this->get_logger(), "Planning failed!");
        }
    }

    void get_status(const json& cmd)
    {
        std::string arm = cmd.value("arm", "left");
        std::string end_effector = (arm == "left") ? "elfin_link6_left" : "elfin_link6_right";

        if (!got_joint_state_) {
            RCLCPP_ERROR(this->get_logger(), "No joint state received yet!");
            return;
        }

        auto current_pose = getPoseFromTF(end_effector);
        auto current_joints = get_current_joints(arm);

        RCLCPP_INFO(this->get_logger(), "=== %s ARM STATUS ===", arm.c_str());
        RCLCPP_INFO(this->get_logger(), "Position: [%.3f, %.3f, %.3f]",
            current_pose.position.x, current_pose.position.y, current_pose.position.z);
        RCLCPP_INFO(this->get_logger(), "Joints: [%.3f, %.3f, %.3f, %.3f, %.3f, %.3f]",
            current_joints[0], current_joints[1], current_joints[2],
            current_joints[3], current_joints[4], current_joints[5]);
    }

    std::shared_ptr<moveit::planning_interface::MoveGroupInterface> left_arm_;
    std::shared_ptr<moveit::planning_interface::MoveGroupInterface> right_arm_;
    rclcpp::Subscription<std_msgs::msg::String>::SharedPtr command_sub_;
    rclcpp::Subscription<sensor_msgs::msg::JointState>::SharedPtr joint_state_sub_;

    sensor_msgs::msg::JointState latest_joint_state_;
    std::mutex joint_state_mutex_;
    bool got_joint_state_ = false;

    std::unique_ptr<tf2_ros::Buffer> tf_buffer_;
    std::shared_ptr<tf2_ros::TransformListener> tf_listener_;
};

int main(int argc, char** argv)
{
    rclcpp::init(argc, argv);

    auto controller = std::make_shared<RobotController>();
    controller->initialize();

    rclcpp::spin(controller);
    rclcpp::shutdown();
    return 0;
}
