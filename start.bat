@echo off
chcp 65001 >nul
title 智能招聘 RAG 推荐系统
setlocal enabledelayedexpansion

:: ============================================================
::  智能招聘 RAG 推荐系统 - 一键启动脚本
::  用法:
::    start.bat           启动全部服务
::    start.bat stop      停止全部服务
::    start.bat restart   重启全部服务
::    start.bat status    查看服务状态
::    start.bat logs      查看应用日志
:: ============================================================

set "PROJECT_DIR=%~dp0"
cd /d "%PROJECT_DIR%"

:: ── 选择操作 ──
if "%~1"=="stop"   goto :stop
if "%~1"=="restart" goto :restart
if "%~1"=="status"  goto :status
if "%~1"=="logs"    goto :logs

:start
echo.
echo ╔══════════════════════════════════════════════════════╗
echo ║     智能招聘 RAG 推荐系统 - 正在启动...             ║
echo ╚══════════════════════════════════════════════════════╝
echo.

:: 检查 Docker
echo [1/4] 检查 Docker 环境...
docker info >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] Docker Desktop 未运行，请先启动 Docker Desktop
    pause
    exit /b 1
)
echo    ✓ Docker 已就绪

:: 检查 .env 文件
echo [2/4] 检查配置文件...
if not exist ".env" (
    echo [警告] .env 文件不存在，正在从 .env.example 复制...
    copy .env.example .env >nul
    echo    ⚠ 请编辑 .env 填写 API Key 后重新运行
    pause
    exit /b 1
)
echo    ✓ .env 已就绪

:: 启动服务
echo [3/4] 启动容器服务 (MongoDB + Milvus + Redis + FastAPI + Streamlit)...
docker compose up -d --wait --wait-timeout 120 2>&1 | findstr /v /c:"depends_on" >nul
if %errorlevel% neq 0 (
    docker compose up -d 2>&1
)
echo    ✓ 服务已启动

:: 等待健康检查
echo [4/4] 等待服务就绪...
set COUNT=0
:wait_loop
set /a COUNT+=1
if !COUNT! gtr 30 (
    echo [警告] 服务启动超时，手动检查: docker compose ps
    goto :done
)
docker compose ps app --format "{{.Health}}" 2>nul | findstr "healthy" >nul
if %errorlevel% equ 0 goto :done
timeout /t 2 /nobreak >nul
goto :wait_loop

:done
echo    ✓ 所有服务已就绪
echo.
echo ╔══════════════════════════════════════════════════════╗
echo ║  ✓ 启动成功！                                       ║
echo ║                                                     ║
echo ║  API 文档:    http://localhost:8000/docs             ║
echo ║  Web 界面:    http://localhost:8501                  ║
echo ║  健康检查:    http://localhost:8000/health           ║
echo ║                                                     ║
echo ║  默认账号:    admin / admin123                       ║
echo ║                                                     ║
echo ║  start.bat status   查看状态                         ║
echo ║  start.bat logs     查看日志                         ║
echo ║  start.bat stop     停止服务                         ║
echo ╚══════════════════════════════════════════════════════╝
echo.

:: 打开浏览器
start "" http://localhost:8501
exit /b 0

:stop
echo 正在停止全部服务...
docker compose down
echo 服务已停止
exit /b 0

:restart
echo 正在重启...
call :stop
timeout /t 3 /nobreak >nul
goto :start

:status
echo.
echo ╔══════════════════════════════════════════════════════╗
echo ║              服务状态                                ║
echo ╚══════════════════════════════════════════════════════╝
echo.
docker compose ps
echo.
echo 端口占用:
netstat -ano | findstr /c:"8000 " /c:"8501 " /c:"19530 " /c:"27017 " /c:"6379 " 2>nul
echo.
echo API 健康检查:
curl -s http://localhost:8000/health 2>nul || echo   API 不可达
echo.
exit /b 0

:logs
echo 显示最近 100 行日志 (Ctrl+C 退出)...
docker compose logs app --tail 100 -f
exit /b 0
