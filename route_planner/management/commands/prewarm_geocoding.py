from django.core.management.base import BaseCommand
from route_planner.fuel_service import load_fuel_data
from route_planner.optimizer import geocode_fuel_data


class Command(BaseCommand):
    help = (
        "Pre-geocode all unique fuel stop locations (City+State) via Nominatim "
        "and save to data/fuel_geocoded.json. The API then uses this file so it "
        "never calls Nominatim on user requests. Run once (or after adding new "
        "fuel data). Respects Nominatim's 1 req/s limit, so expect ~1 second "
        "per new location (e.g. 15–40 min for a full first run)."
    )

    def handle(self, *args, **kwargs):
        self.stdout.write("Loading fuel data...")
        fuel_df = load_fuel_data()
        n_rows = len(fuel_df)

        self.stdout.write(
            f"Geocoding unique City+State for {n_rows} fuel stops "
            "(only missing locations are requested)..."
        )
        geocode_fuel_data(fuel_df)
        self.stdout.write(
            self.style.SUCCESS(
                "Done! All fuel stops geocoded and saved to data/fuel_geocoded.json"
            )
        )