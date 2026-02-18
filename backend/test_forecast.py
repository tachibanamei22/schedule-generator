"""Quick test to verify forecast positional mapping."""
from data_parser import load_forecast_data

# Simulate WFM dates (December 2025)
dec_dates = [f'2025-12-{d:02d}' for d in range(1, 32)]

f = load_forecast_data(r'uploads\Simulation Schedule (002).xlsx', dec_dates)

print("=== Forecast mapped to Dec 2025 ===")
print(f"Dec 1, hour 0 demand: {f.requirements['2025-12-01'][0]}")
print(f"Dec 1, hour 8 demand: {f.requirements['2025-12-01'][8]}")
print(f"Dec 1, hour 14 demand: {f.requirements['2025-12-01'][14]}")
print(f"Dec 31, hour 10 demand: {f.requirements['2025-12-31'][10]}")

total_dec1 = sum(f.requirements['2025-12-01'].values())
total_dec31 = sum(f.requirements['2025-12-31'].values())
print(f"\nTotal demand Dec 1: {total_dec1}")
print(f"Total demand Dec 31: {total_dec31}")
print(f"Dates with forecast: {len([d for d in dec_dates if d in f.requirements])}")
