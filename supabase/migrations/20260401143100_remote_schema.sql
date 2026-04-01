drop extension if exists "pg_net";

revoke delete on table "public"."bot_logs" from "anon";

revoke insert on table "public"."bot_logs" from "anon";

revoke references on table "public"."bot_logs" from "anon";

revoke select on table "public"."bot_logs" from "anon";

revoke trigger on table "public"."bot_logs" from "anon";

revoke truncate on table "public"."bot_logs" from "anon";

revoke update on table "public"."bot_logs" from "anon";

revoke delete on table "public"."bot_logs" from "authenticated";

revoke insert on table "public"."bot_logs" from "authenticated";

revoke references on table "public"."bot_logs" from "authenticated";

revoke select on table "public"."bot_logs" from "authenticated";

revoke trigger on table "public"."bot_logs" from "authenticated";

revoke truncate on table "public"."bot_logs" from "authenticated";

revoke update on table "public"."bot_logs" from "authenticated";

revoke delete on table "public"."bot_logs" from "service_role";

revoke insert on table "public"."bot_logs" from "service_role";

revoke references on table "public"."bot_logs" from "service_role";

revoke select on table "public"."bot_logs" from "service_role";

revoke trigger on table "public"."bot_logs" from "service_role";

revoke truncate on table "public"."bot_logs" from "service_role";

revoke update on table "public"."bot_logs" from "service_role";

revoke delete on table "public"."trades" from "anon";

revoke insert on table "public"."trades" from "anon";

revoke references on table "public"."trades" from "anon";

revoke select on table "public"."trades" from "anon";

revoke trigger on table "public"."trades" from "anon";

revoke truncate on table "public"."trades" from "anon";

revoke update on table "public"."trades" from "anon";

revoke delete on table "public"."trades" from "authenticated";

revoke insert on table "public"."trades" from "authenticated";

revoke references on table "public"."trades" from "authenticated";

revoke select on table "public"."trades" from "authenticated";

revoke trigger on table "public"."trades" from "authenticated";

revoke truncate on table "public"."trades" from "authenticated";

revoke update on table "public"."trades" from "authenticated";

revoke delete on table "public"."trades" from "service_role";

revoke insert on table "public"."trades" from "service_role";

revoke references on table "public"."trades" from "service_role";

revoke select on table "public"."trades" from "service_role";

revoke trigger on table "public"."trades" from "service_role";

revoke truncate on table "public"."trades" from "service_role";

revoke update on table "public"."trades" from "service_role";

alter table "public"."bot_logs" alter column "id" set default nextval('bot_logs_id_seq'::regclass);


