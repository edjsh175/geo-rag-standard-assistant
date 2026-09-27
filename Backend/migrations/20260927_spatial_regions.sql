-- 20260927_spatial_regions.sql
-- Single authoritative schema definition for spatial_regions table used by SpatialService and GIS capabilities.

CREATE EXTENSION IF NOT EXISTS postgis;

CREATE TABLE IF NOT EXISTS spatial_regions (
    id SERIAL PRIMARY KEY,
    adcode VARCHAR(20) NOT NULL,
    region_name VARCHAR(100) NOT NULL,
    geometry GEOMETRY(MultiPolygon, 4326),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_spatial_regions_adcode UNIQUE (adcode)
);

CREATE INDEX IF NOT EXISTS idx_spatial_regions_geometry
    ON spatial_regions USING GIST (geometry);

CREATE INDEX IF NOT EXISTS idx_spatial_regions_region_name
    ON spatial_regions (region_name);
