-- Fly Script for Roblox
-- Toggle: press Q to fly / unfly

local Players = game:GetService("Players")
local RunService = game:GetService("RunService")
local UserInputService = game:GetService("UserInputService")

local player = Players.LocalPlayer
local camera = workspace.CurrentCamera

local flying = false
local flySpeed = 60
local connection

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
    print("[Fly] 已啟動 | 速度: " .. flySpeed)
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
    print("[Fly] 已關閉")
end

-- 按 Q 切換飛行
UserInputService.InputBegan:Connect(function(input, gameProcessed)
    if gameProcessed then return end
    if input.KeyCode == Enum.KeyCode.Q then
        if flying then
            disableFly()
        else
            enableFly()
        end
    end
end)

-- 角色重生時自動清理
player.CharacterAdded:Connect(function()
    if flying then
        flying = false
        if connection then
            connection:Disconnect()
            connection = nil
        end
    end
end)

print("[Fly] 已載入 | 按 Q 切換飛行")
