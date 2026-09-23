-- Fly Script with UI
-- Toggle: press Q or click button

local Players = game:GetService("Players")
local RunService = game:GetService("RunService")
local UserInputService = game:GetService("UserInputService")
local TweenService = game:GetService("TweenService")

local player = Players.LocalPlayer
local playerGui = player:WaitForChild("PlayerGui")
local camera = workspace.CurrentCamera

local flying = false
local flySpeed = 60
local connection

-- ── UI ────────────────────────────────────────────────────────────────────────

local screenGui = Instance.new("ScreenGui")
screenGui.Name = "FlyGui"
screenGui.ResetOnSpawn = false
screenGui.ZIndexBehavior = Enum.ZIndexBehavior.Sibling
screenGui.Parent = playerGui

-- 主視窗
local frame = Instance.new("Frame")
frame.Name = "Main"
frame.Size = UDim2.new(0, 200, 0, 160)
frame.Position = UDim2.new(0, 20, 0.5, -80)
frame.BackgroundColor3 = Color3.fromRGB(18, 18, 28)
frame.BorderSizePixel = 0
frame.Active = true
frame.Draggable = true
frame.Parent = screenGui

local corner = Instance.new("UICorner")
corner.CornerRadius = UDim.new(0, 10)
corner.Parent = frame

local stroke = Instance.new("UIStroke")
stroke.Color = Color3.fromRGB(100, 100, 200)
stroke.Thickness = 1.5
stroke.Parent = frame

-- 標題列
local titleBar = Instance.new("Frame")
titleBar.Size = UDim2.new(1, 0, 0, 36)
titleBar.BackgroundColor3 = Color3.fromRGB(30, 30, 50)
titleBar.BorderSizePixel = 0
titleBar.Parent = frame

local titleCorner = Instance.new("UICorner")
titleCorner.CornerRadius = UDim.new(0, 10)
titleCorner.Parent = titleBar

-- 補底部圓角
local titleFix = Instance.new("Frame")
titleFix.Size = UDim2.new(1, 0, 0, 10)
titleFix.Position = UDim2.new(0, 0, 1, -10)
titleFix.BackgroundColor3 = Color3.fromRGB(30, 30, 50)
titleFix.BorderSizePixel = 0
titleFix.Parent = titleBar

local titleLabel = Instance.new("TextLabel")
titleLabel.Size = UDim2.new(1, 0, 1, 0)
titleLabel.BackgroundTransparency = 1
titleLabel.Text = "✈  Fly Script"
titleLabel.TextColor3 = Color3.fromRGB(200, 200, 255)
titleLabel.TextSize = 15
titleLabel.Font = Enum.Font.GothamBold
titleLabel.Parent = titleBar

-- 狀態標籤
local statusLabel = Instance.new("TextLabel")
statusLabel.Size = UDim2.new(1, 0, 0, 24)
statusLabel.Position = UDim2.new(0, 0, 0, 44)
statusLabel.BackgroundTransparency = 1
statusLabel.Text = "狀態：關閉"
statusLabel.TextColor3 = Color3.fromRGB(255, 100, 100)
statusLabel.TextSize = 13
statusLabel.Font = Enum.Font.Gotham
statusLabel.Parent = frame

-- 速度標籤
local speedLabel = Instance.new("TextLabel")
speedLabel.Size = UDim2.new(1, -20, 0, 20)
speedLabel.Position = UDim2.new(0, 10, 0, 72)
speedLabel.BackgroundTransparency = 1
speedLabel.Text = "速度：" .. flySpeed
speedLabel.TextColor3 = Color3.fromRGB(180, 180, 230)
speedLabel.TextSize = 12
speedLabel.Font = Enum.Font.Gotham
speedLabel.TextXAlignment = Enum.TextXAlignment.Left
speedLabel.Parent = frame

-- 速度 Slider 背景
local sliderBg = Instance.new("Frame")
sliderBg.Size = UDim2.new(1, -20, 0, 8)
sliderBg.Position = UDim2.new(0, 10, 0, 96)
sliderBg.BackgroundColor3 = Color3.fromRGB(50, 50, 80)
sliderBg.BorderSizePixel = 0
sliderBg.Parent = frame

local sliderBgCorner = Instance.new("UICorner")
sliderBgCorner.CornerRadius = UDim.new(1, 0)
sliderBgCorner.Parent = sliderBg

-- 速度 Slider 填充
local sliderFill = Instance.new("Frame")
sliderFill.Size = UDim2.new(flySpeed / 200, 0, 1, 0)
sliderFill.BackgroundColor3 = Color3.fromRGB(100, 100, 255)
sliderFill.BorderSizePixel = 0
sliderFill.Parent = sliderBg

local sliderFillCorner = Instance.new("UICorner")
sliderFillCorner.CornerRadius = UDim.new(1, 0)
sliderFillCorner.Parent = sliderFill

-- Slider 拖曳點
local sliderKnob = Instance.new("Frame")
sliderKnob.Size = UDim2.new(0, 16, 0, 16)
sliderKnob.Position = UDim2.new(flySpeed / 200, -8, 0.5, -8)
sliderKnob.BackgroundColor3 = Color3.fromRGB(200, 200, 255)
sliderKnob.BorderSizePixel = 0
sliderKnob.ZIndex = 2
sliderKnob.Parent = sliderBg

local knobCorner = Instance.new("UICorner")
knobCorner.CornerRadius = UDim.new(1, 0)
knobCorner.Parent = sliderKnob

-- 飛行切換按鈕
local toggleBtn = Instance.new("TextButton")
toggleBtn.Size = UDim2.new(1, -20, 0, 32)
toggleBtn.Position = UDim2.new(0, 10, 0, 116)
toggleBtn.BackgroundColor3 = Color3.fromRGB(60, 60, 120)
toggleBtn.BorderSizePixel = 0
toggleBtn.Text = "開始飛行  [Q]"
toggleBtn.TextColor3 = Color3.fromRGB(220, 220, 255)
toggleBtn.TextSize = 13
toggleBtn.Font = Enum.Font.GothamBold
toggleBtn.Parent = frame

local btnCorner = Instance.new("UICorner")
btnCorner.CornerRadius = UDim.new(0, 8)
btnCorner.Parent = toggleBtn

-- ── Slider 邏輯 ───────────────────────────────────────────────────────────────

local dragging = false

local function updateSlider(x)
    local bgPos = sliderBg.AbsolutePosition.X
    local bgSize = sliderBg.AbsoluteSize.X
    local ratio = math.clamp((x - bgPos) / bgSize, 0, 1)
    flySpeed = math.floor(ratio * 200)
    if flySpeed < 1 then flySpeed = 1 end

    sliderFill.Size = UDim2.new(ratio, 0, 1, 0)
    sliderKnob.Position = UDim2.new(ratio, -8, 0.5, -8)
    speedLabel.Text = "速度：" .. flySpeed
end

sliderBg.InputBegan:Connect(function(input)
    if input.UserInputType == Enum.UserInputType.MouseButton1 then
        dragging = true
        updateSlider(input.Position.X)
    end
end)

UserInputService.InputChanged:Connect(function(input)
    if dragging and input.UserInputType == Enum.UserInputType.MouseMovement then
        updateSlider(input.Position.X)
    end
end)

UserInputService.InputEnded:Connect(function(input)
    if input.UserInputType == Enum.UserInputType.MouseButton1 then
        dragging = false
    end
end)

-- ── 飛行邏輯 ──────────────────────────────────────────────────────────────────

local function setUI(isFlying)
    if isFlying then
        statusLabel.Text = "狀態：飛行中 ✈"
        statusLabel.TextColor3 = Color3.fromRGB(100, 255, 150)
        toggleBtn.Text = "停止飛行  [Q]"
        toggleBtn.BackgroundColor3 = Color3.fromRGB(80, 40, 40)
        TweenService:Create(stroke, TweenInfo.new(0.3), {
            Color = Color3.fromRGB(100, 255, 150)
        }):Play()
    else
        statusLabel.Text = "狀態：關閉"
        statusLabel.TextColor3 = Color3.fromRGB(255, 100, 100)
        toggleBtn.Text = "開始飛行  [Q]"
        toggleBtn.BackgroundColor3 = Color3.fromRGB(60, 60, 120)
        TweenService:Create(stroke, TweenInfo.new(0.3), {
            Color = Color3.fromRGB(100, 100, 200)
        }):Play()
    end
end

local function getCharacter()
    return player.Character or player.CharacterAdded:Wait()
end

local function enableFly()
    local char = getCharacter()
    local hrp = char:FindFirstChild("HumanoidRootPart")
    local humanoid = char:FindFirstChildOfClass("Humanoid")
    if not hrp or not humanoid then return end

    humanoid.PlatformStand = true

    local bodyVelocity = Instance.new("BodyVelocity")
    bodyVelocity.Velocity = Vector3.zero
    bodyVelocity.MaxForce = Vector3.new(1e5, 1e5, 1e5)
    bodyVelocity.Parent = hrp

    local bodyGyro = Instance.new("BodyGyro")
    bodyGyro.MaxTorque = Vector3.new(1e5, 1e5, 1e5)
    bodyGyro.P = 1e4
    bodyGyro.Parent = hrp

    connection = RunService.RenderStepped:Connect(function()
        local char2 = player.Character
        if not char2 then return end
        local hrp2 = char2:FindFirstChild("HumanoidRootPart")
        if not hrp2 then return end

        local cf = camera.CFrame
        local velocity = Vector3.zero

        if UserInputService:IsKeyDown(Enum.KeyCode.W) then
            velocity = velocity + cf.LookVector
        end
        if UserInputService:IsKeyDown(Enum.KeyCode.S) then
            velocity = velocity - cf.LookVector
        end
        if UserInputService:IsKeyDown(Enum.KeyCode.A) then
            velocity = velocity - cf.RightVector
        end
        if UserInputService:IsKeyDown(Enum.KeyCode.D) then
            velocity = velocity + cf.RightVector
        end
        if UserInputService:IsKeyDown(Enum.KeyCode.Space) then
            velocity = velocity + Vector3.new(0, 1, 0)
        end
        if UserInputService:IsKeyDown(Enum.KeyCode.LeftControl) then
            velocity = velocity - Vector3.new(0, 1, 0)
        end

        if velocity.Magnitude > 0 then
            velocity = velocity.Unit * flySpeed
        end

        bodyVelocity.Velocity = velocity
        bodyGyro.CFrame = cf
    end)

    flying = true
    setUI(true)
end

local function disableFly()
    local char = player.Character
    if char then
        local hrp = char:FindFirstChild("HumanoidRootPart")
        local humanoid = char:FindFirstChildOfClass("Humanoid")
        if hrp then
            local bv = hrp:FindFirstChildOfClass("BodyVelocity")
            local bg = hrp:FindFirstChildOfClass("BodyGyro")
            if bv then bv:Destroy() end
            if bg then bg:Destroy() end
        end
        if humanoid then
            humanoid.PlatformStand = false
        end
    end

    if connection then
        connection:Disconnect()
        connection = nil
    end

    flying = false
    setUI(false)
end

local function toggle()
    if flying then disableFly() else enableFly() end
end

-- 按鈕點擊
toggleBtn.MouseButton1Click:Connect(toggle)

-- Q 鍵切換
UserInputService.InputBegan:Connect(function(input, gameProcessed)
    if gameProcessed then return end
    if input.KeyCode == Enum.KeyCode.Q then toggle() end
end)

-- 角色重生清理
player.CharacterAdded:Connect(function()
    if flying then
        flying = false
        if connection then
            connection:Disconnect()
            connection = nil
        end
        setUI(false)
    end
end)

print("[Fly] 已載入 | 按 Q 或點擊按鈕切換飛行")
