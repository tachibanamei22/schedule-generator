"""
FastAPI server for WFM Schedule Generator.
"""
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import shutil
import os
import json
import tempfile
from pathlib import Path

# Load .env file for local development
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")
except ImportError:
    pass  # python-dotenv not installed, rely on system env vars

from data_parser import load_wfm_data, load_forecast_data
from solver import ScheduleSolver
from rule_engine import parse_regulations_with_llm, rules_to_json

app = FastAPI(
    title="WFM Schedule Generator",
    description="AI-powered workforce schedule generator using OR-Tools CP-SAT",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Store uploaded data and results in memory
app_state = {
    "wfm_data": None,
    "results": None,
    "uploaded_file": None,
    "forecast_uploaded": False,
    "forecast_file": None,
    "parsed_rules": None
}

UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)


@app.get("/api/health")
async def health_check():
    return {"status": "ok", "message": "WFM Schedule Generator API is running"}


@app.post("/api/upload")
async def upload_file(file: UploadFile = File(...)):
    """Upload a WFM Data Excel file."""
    if not file.filename.endswith(('.xlsx', '.xls')):
        raise HTTPException(400, "Please upload an Excel file (.xlsx)")
    
    filepath = UPLOAD_DIR / file.filename
    with open(filepath, "wb") as f:
        shutil.copyfileobj(file.file, f)
    
    try:
        wfm_data = load_wfm_data(str(filepath))
        app_state["wfm_data"] = wfm_data
        app_state["uploaded_file"] = str(filepath)
        
        # Parse regulations with GPT
        parsed_rules = parse_regulations_with_llm(wfm_data.regulations)
        app_state["parsed_rules"] = parsed_rules
        
        return {
            "message": "File uploaded and parsed successfully",
            "data": {
                "num_agents": len(wfm_data.agents),
                "num_dates": len(wfm_data.dates),
                "num_shift_codes": len(wfm_data.shift_codes),
                "num_leave_requests": len(wfm_data.leave_requests),
                "num_regulations": len(wfm_data.regulations),
                "agents": [
                    {
                        "id": a.id,
                        "name": a.name,
                        "role": a.role,
                        "channel": a.channel,
                        "gender": a.gender
                    }
                    for a in wfm_data.agents
                ],
                "dates": wfm_data.dates,
                "regulations": wfm_data.regulations,
                "parsed_rules": rules_to_json(parsed_rules),
                "leave_requests": [
                    {
                        "employee_id": lr.employee_id,
                        "employee_name": lr.employee_name,
                        "leave_type": lr.leave_type,
                        "date": lr.date.strftime('%Y-%m-%d')
                    }
                    for lr in wfm_data.leave_requests
                ]
            }
        }
    except Exception as e:
        raise HTTPException(500, f"Error parsing file: {str(e)}")


@app.post("/api/upload-forecast")
async def upload_forecast(file: UploadFile = File(...)):
    """Upload a Simulation Schedule / Forecast Excel file."""
    if app_state["wfm_data"] is None:
        raise HTTPException(400, "Please upload WFM data file first")
    
    if not file.filename.endswith(('.xlsx', '.xls')):
        raise HTTPException(400, "Please upload an Excel file (.xlsx)")
    
    filepath = UPLOAD_DIR / file.filename
    with open(filepath, "wb") as f:
        shutil.copyfileobj(file.file, f)
    
    try:
        wfm_data = app_state["wfm_data"]
        
        # Load forecast demand, mapping positionally to WFM dates
        # (forecast col 1 = WFM date 1, col 2 = WFM date 2, etc.)
        forecast = load_forecast_data(str(filepath), wfm_data.dates)
        wfm_data.forecast = forecast
        
        app_state["forecast_uploaded"] = True
        app_state["forecast_file"] = str(filepath)
        
        # Calculate summary stats
        wfm_dates = wfm_data.dates
        total_demand = 0
        for date_str in wfm_dates:
            reqs = forecast.requirements.get(date_str, {})
            total_demand += sum(reqs.values())
        avg_daily = total_demand // len(wfm_dates) if wfm_dates else 0
        
        return {
            "message": "Forecast data uploaded and parsed successfully",
            "data": {
                "num_dates": len(wfm_dates),
                "date_range": f"{wfm_dates[0]} to {wfm_dates[-1]}" if wfm_dates else "N/A",
                "dates": wfm_dates,
                "avg_daily_demand": avg_daily,
                "total_demand": total_demand,
                "leave_requests_in_range": len([
                    lr for lr in wfm_data.leave_requests
                    if lr.date.strftime('%Y-%m-%d') in wfm_dates
                ]),
                "leave_requests_total": len(wfm_data.leave_requests)
            }
        }
    except Exception as e:
        raise HTTPException(500, f"Error parsing forecast file: {str(e)}")


@app.post("/api/generate")
async def generate_schedule(time_limit: int = 60):
    """Generate an optimized schedule using CP-SAT solver."""
    if app_state["wfm_data"] is None:
        raise HTTPException(400, "Please upload a WFM data file first")
    
    try:
        solver = ScheduleSolver(app_state["wfm_data"])
        solver.build_model(parsed_rules=app_state.get("parsed_rules"))
        
        success = solver.solve(time_limit_seconds=time_limit)
        
        if not success:
            raise HTTPException(
                500, 
                "Solver could not find a feasible schedule. "
                "Try relaxing constraints or increasing the time limit."
            )
        
        results = solver.get_results_json()
        app_state["results"] = results
        
        return results
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Error generating schedule: {str(e)}")


@app.get("/api/results")
async def get_results():
    """Get the most recent schedule results."""
    if app_state["results"] is None:
        raise HTTPException(404, "No schedule has been generated yet")
    
    return app_state["results"]


@app.get("/api/export")
async def export_excel():
    """Export the generated schedule as an Excel file."""
    if app_state["results"] is None:
        raise HTTPException(404, "No schedule has been generated yet")
    
    try:
        import openpyxl
        from openpyxl.styles import PatternFill, Font, Alignment, Border, Side
        
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Generated Schedule"
        
        results = app_state["results"]
        dates = results["dates"]
        agents = results["agents"]
        
        # Styles
        header_fill = PatternFill(start_color="1a1a2e", end_color="1a1a2e", fill_type="solid")
        header_font = Font(color="FFFFFF", bold=True, size=10)
        off_fill = PatternFill(start_color="e8f5e9", end_color="e8f5e9", fill_type="solid")
        morning_fill = PatternFill(start_color="e3f2fd", end_color="e3f2fd", fill_type="solid")
        evening_fill = PatternFill(start_color="fff3e0", end_color="fff3e0", fill_type="solid")
        leave_fill = PatternFill(start_color="fce4ec", end_color="fce4ec", fill_type="solid")
        thin_border = Border(
            left=Side(style='thin'),
            right=Side(style='thin'),
            top=Side(style='thin'),
            bottom=Side(style='thin')
        )
        
        # Headers
        headers = ["ID", "Name", "Role", "Channel", "Gender"] + dates
        for col, header in enumerate(headers, 1):
            cell = ws.cell(row=1, column=col, value=header)
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal='center')
            cell.border = thin_border
        
        # Data rows
        for row_idx, agent in enumerate(agents, 2):
            ws.cell(row=row_idx, column=1, value=agent['id']).border = thin_border
            ws.cell(row=row_idx, column=2, value=agent['name']).border = thin_border
            ws.cell(row=row_idx, column=3, value=agent['role']).border = thin_border
            ws.cell(row=row_idx, column=4, value=agent['channel']).border = thin_border
            ws.cell(row=row_idx, column=5, value=agent['gender']).border = thin_border
            
            for col_idx, date in enumerate(dates, 6):
                shift = agent['schedule'].get(date, 'OFF')
                cell = ws.cell(row=row_idx, column=col_idx, value=shift)
                cell.alignment = Alignment(horizontal='center')
                cell.border = thin_border
                
                if shift == 'OFF':
                    cell.fill = off_fill
                elif shift == '03:00':
                    cell.fill = morning_fill
                elif shift == '20:00':
                    cell.fill = evening_fill
                elif shift in ('Leave', 'Resign'):
                    cell.fill = leave_fill
        
        # Auto-width
        for col in ws.columns:
            max_length = max(len(str(cell.value or "")) for cell in col)
            ws.column_dimensions[col[0].column_letter].width = min(max_length + 2, 15)
        
        # Coverage stats sheet
        ws2 = wb.create_sheet("Coverage Stats")
        coverage = results.get("coverage", {})
        
        cov_headers = ["Date", "03:00 Shift", "20:00 Shift", "Total Working", "OFF", "Leave", "Demand (avg)"]
        for col, header in enumerate(cov_headers, 1):
            cell = ws2.cell(row=1, column=col, value=header)
            cell.fill = header_fill
            cell.font = header_font
            cell.border = thin_border
        
        for row_idx, date in enumerate(dates, 2):
            stats = coverage.get(date, {})
            ws2.cell(row=row_idx, column=1, value=date).border = thin_border
            ws2.cell(row=row_idx, column=2, value=stats.get('shift_03_count', 0)).border = thin_border
            ws2.cell(row=row_idx, column=3, value=stats.get('shift_20_count', 0)).border = thin_border
            ws2.cell(row=row_idx, column=4, value=stats.get('total_working', 0)).border = thin_border
            ws2.cell(row=row_idx, column=5, value=stats.get('off_count', 0)).border = thin_border
            ws2.cell(row=row_idx, column=6, value=stats.get('leave_count', 0)).border = thin_border
            ws2.cell(row=row_idx, column=7, value=stats.get('forecast_demand', 0)).border = thin_border
        
        export_path = UPLOAD_DIR / "generated_schedule.xlsx"
        wb.save(str(export_path))
        
        return FileResponse(
            str(export_path),
            filename="WFM_Generated_Schedule.xlsx",
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    except Exception as e:
        raise HTTPException(500, f"Error exporting: {str(e)}")


# ─── Serve frontend static files ───
frontend_dir = Path(__file__).parent.parent / "frontend"
if frontend_dir.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
