# NYC 311 Dataset — Official Schema Reference

**Source:** Socrata dataset metadata API for "311 Service Requests from 2020 to Present" (dataset id `erm2-nwe9`)
**URL:** https://data.cityofnewyork.us/api/views/erm2-nwe9.json
**Fetched:** 2026-10-12/13
**Why this file exists:** confirms the dataset's authoritative, defined schema (48 columns) independent of what happens to appear in any sampled or even fully-scanned slice of actual row data. A full scan of all 3,963,880 backfilled rows found only 44 of these 48 fields ever populated — the missing 4 are the `:@computed_region_*` fields below, which are part of the official schema but never had a value anywhere in this project's extraction window. See `notes/decisions/0007-staging-append-only-history.md` and the staging table design discussion for how this schema maps to the staging table's 48 source columns.

Note: a literal raw download of the JSON file was attempted but isn't possible in this environment — direct HTTP requests (curl) are blocked by egress policy both in the cloud session and from this machine's shell, and the available web-fetch tool summarizes/extracts rather than returning raw bytes. This table is a faithful, complete transcription of all 48 entries in the API response's `columns` array (fieldName, dataTypeName, description), fetched and verified live.

| # | fieldName | dataTypeName | description |
|---|-----------|--------------|--------------|
| 1 | unique_key | text | Unique identifier of a Service Request (SR) in the open data set |
| 2 | created_date | calendar_date | Date SR was created |
| 3 | closed_date | calendar_date | Date SR was closed by responding agency |
| 4 | agency | text | Acronym of responding City Government Agency |
| 5 | agency_name | text | Full Agency name of responding City Government Agency |
| 6 | complaint_type | text | First level of a hierarchy identifying the topic of the incident or condition. Broadly describes the topic and is defined by the responding agencies. |
| 7 | descriptor | text | Associated to the Problem (Complaint Type); provides further detail on the incident or condition. Not always required. |
| 8 | descriptor_2 | text | A third level of detail beyond the Problem Detail (Descriptor). Not used by every category of issue. |
| 9 | location_type | text | Describes the type of location used in the address information |
| 10 | incident_zip | text | Incident location zip code, provided by geo validation |
| 11 | incident_address | text | House number of incident address provided by submitter |
| 12 | street_name | text | Street name of incident address provided by the submitter |
| 13 | cross_street_1 | text | First cross street based on the geo validated incident location |
| 14 | cross_street_2 | text | Second cross street based on the geo validated incident location |
| 15 | intersection_street_1 | text | First intersecting street based on geo validated incident location |
| 16 | intersection_street_2 | text | Second intersecting street based on geo validated incident location |
| 17 | address_type | text | Type of incident location information available |
| 18 | city | text | City of the incident location provided by geovalidation |
| 19 | landmark | text | If the incident location is identified as a Landmark, the name of the landmark will display here |
| 20 | facility_type | text | If available, describes the type of city facility associated to the SR |
| 21 | status | text | Status of SR submitted |
| 22 | due_date | calendar_date | Date when responding agency is expected to update the SR, based on Complaint Type and internal SLAs |
| 23 | resolution_description | text | Describes the last action taken on the SR by the responding agency; may describe next/future steps |
| 24 | resolution_action_updated_date | calendar_date | Date when responding agency last updated the SR |
| 25 | community_board | text | Provided by geovalidation |
| 26 | council_district | text | The City Council district where the service request is located |
| 27 | police_precinct | text | The NYPD precinct where the service request is located |
| 28 | bbl | text | Borough Block and Lot, provided by geovalidation — parcel number identifying buildings/properties in NYC |
| 29 | borough | text | Provided by the submitter and confirmed by geovalidation |
| 30 | x_coordinate_state_plane | number | Geo validated X coordinate of the incident location |
| 31 | y_coordinate_state_plane | number | Geo validated Y coordinate of the incident location |
| 32 | open_data_channel_type | text | Indicates how the SR was submitted to 311 (Phone, Online, Mobile, Other, Unknown) |
| 33 | park_facility_name | text | If the incident location is a Parks Dept facility, the name of the facility |
| 34 | park_borough | text | The borough of incident if it is a Parks Dept facility |
| 35 | vehicle_type | text | If the incident is a taxi, describes the type of TLC vehicle |
| 36 | taxi_company_borough | text | If the incident is identified as a taxi, the borough of the taxi company |
| 37 | taxi_pick_up_location | text | If the incident is identified as a taxi, the taxi pick up location |
| 38 | bridge_highway_name | text | If the incident is identified as a Bridge/Highway, the name |
| 39 | bridge_highway_direction | text | If the incident is identified as a Bridge/Highway, the direction where the issue took place |
| 40 | road_ramp | text | If the incident location was Bridge/Highway, differentiates whether the issue was on the Road or the Ramp |
| 41 | bridge_highway_segment | text | Additional information on the section of the Bridge/Highway where the incident took place |
| 42 | latitude | number | Geo based latitude of the incident location |
| 43 | longitude | number | Geo based longitude of the incident location |
| 44 | location | point | Combination of the geo based lat & long of the incident location |
| 45 | :@computed_region_f5dn_yrer | number | Auto-created: records which polygon from 'Community Districts' (f5dn-yrer) contains `location` |
| 46 | :@computed_region_yeji_bk3q | number | Auto-created: records which polygon from 'Borough Boundaries' (yeji-bk3q) contains `location` |
| 47 | :@computed_region_sbqj_enih | number | Auto-created: records which polygon from 'Police Precincts' (sbqj-enih) contains `location` |
| 48 | :@computed_region_92fq_4b7q | number | Auto-created: records which polygon from 'City Council Districts' (92fq-4b7q) contains `location` |

**Total: 48 columns.**

## How this maps to the staging table design
All 48 columns above are staged as `TEXT`, except:
- `created_date`, `closed_date`, `due_date`, `resolution_action_updated_date` → `TIMESTAMP` (no timezone — raw source strings carry no offset)
- `location` → `JSONB` (preserves the nested `{type, coordinates}` structure)

Staging keeps every numeric-looking field (`bbl`, `latitude`, `longitude`, `x_coordinate_state_plane`, `y_coordinate_state_plane`, the four `computed_region_*` fields) as `TEXT` as well, despite Socrata's own `number` typing — staging's job is to shape the raw dump into a table without casting or interpreting values; real type casting is a transform-step decision, not a staging-step one.
