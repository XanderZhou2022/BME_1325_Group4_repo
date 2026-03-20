extends Control


func _ready() -> void:
	# 连接按钮信号
	$VBoxContainer/StartButton.pressed.connect(_on_start_button_pressed)
	$VBoxContainer/LoadButton.pressed.connect(_on_load_button_pressed)
	$VBoxContainer/ExitButton.pressed.connect(_on_exit_button_pressed)


func _on_start_button_pressed() -> void:
	# 开始新游戏，加载游戏场景
	get_tree().change_scene_to_file("res://scenes/game.tscn")


func _on_load_button_pressed() -> void:
	# 载入存档游戏
	print("载入游戏功能待实现")
	# 这里可以添加载入存档的逻辑


func _on_exit_button_pressed() -> void:
	# 退出游戏
	get_tree().quit()